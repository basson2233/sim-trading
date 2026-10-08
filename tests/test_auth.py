import sqlite3
import time

import pytest

from app.auth import (AuthError, AuthService, RateLimited, _token_hash, hash_password, validate_password,
                      verify_password)
from app.engine import Engine, TradingError

PW = "correct-horse-1"


@pytest.fixture
def auth(feed):
    return AuthService(Engine(":memory:", feed))


def test_hash_is_salted_scrypt_and_verifies():
    h1, h2 = hash_password(PW), hash_password(PW)
    assert h1.startswith("scrypt$") and PW not in h1
    assert h1 != h2                                   # per-user random salt
    assert verify_password(PW, h1) and verify_password(PW, h2)
    assert not verify_password("wrong-password", h1)
    assert not verify_password(PW, "garbage") and not verify_password(PW, h1.replace("scrypt", "md5"))


def test_password_rules():
    for bad, user in [("short", ""), ("x" * 129, ""), ("alice123", "ALICE123")]:
        with pytest.raises(TradingError):
            validate_password(bad, user)
    validate_password("long-enough", "alice")


def test_register_validation(auth):
    with pytest.raises(TradingError, match="唔一樣"):
        auth.register("alice", PW, PW + "x", "alice@example.com")
    with pytest.raises(TradingError, match="最少"):
        auth.register("alice", "1234567", "1234567", "alice@example.com")
    auth.register("alice", PW, PW, "alice@example.com")
    with pytest.raises(TradingError, match="已經有人用"):
        auth.register("alice", PW, PW, "alice@example.com")
    stored = auth.db.execute("SELECT password_hash FROM users WHERE username='alice'").fetchone()[0]
    assert stored.startswith("scrypt$") and PW not in stored


def test_authenticate(auth):
    auth.register("alice", PW, PW, "alice@example.com")
    assert auth.authenticate("alice", PW)["username"] == "alice"
    with pytest.raises(AuthError, match="用戶名或密碼錯誤"):
        auth.authenticate("alice", "wrong-password")
    with pytest.raises(AuthError, match="用戶名或密碼錯誤"):   # same message for unknown users
        auth.authenticate("nobody", PW)


def test_account_lockout_after_5_failures(auth):
    auth.register("alice", PW, PW, "alice@example.com")
    for _ in range(4):
        with pytest.raises(AuthError):
            auth.authenticate("alice", "nope-nope", ip="1.1.1.1")
    with pytest.raises(RateLimited):
        auth.authenticate("alice", "nope-nope", ip="1.1.1.1")
    with pytest.raises(RateLimited):                       # even the right password is refused while locked
        auth.authenticate("alice", PW, ip="2.2.2.2")
    auth.db.execute("UPDATE users SET locked_until=? WHERE username='alice'", (time.time() - 1,))
    assert auth.authenticate("alice", PW, ip="2.2.2.2")["username"] == "alice"


def test_successful_login_resets_failure_counter(auth):
    auth.register("alice", PW, PW, "alice@example.com")
    for _ in range(4):
        with pytest.raises(AuthError):
            auth.authenticate("alice", "nope-nope")
    auth.authenticate("alice", PW)
    for _ in range(4):
        with pytest.raises(AuthError):
            auth.authenticate("alice", "nope-nope")      # not locked: counter was reset


def test_ip_throttle(auth):
    for i in range(20):
        with pytest.raises(AuthError):
            auth.authenticate(f"ghost{i}", "whatever1", ip="9.9.9.9")
    with pytest.raises(RateLimited):
        auth.authenticate("ghost", "whatever1", ip="9.9.9.9")
    auth.register("alice", PW, PW, "alice@example.com")
    assert auth.authenticate("alice", PW, ip="8.8.8.8")    # other IPs unaffected


def test_sessions(auth):
    uid = auth.register("alice", PW, PW, "alice@example.com")["id"]
    tok = auth.create_session(uid)
    assert auth.session_user(tok)["username"] == "alice"
    assert auth.db.execute("SELECT COUNT(*) FROM sessions WHERE token_hash=?", (tok,)).fetchone()[0] == 0  # raw token not stored
    assert auth.session_user("forged-token") is None and auth.session_user(None) is None
    auth.delete_session(tok)
    assert auth.session_user(tok) is None
    tok2 = auth.create_session(uid)
    auth.db.execute("UPDATE sessions SET expires_at=? WHERE token_hash=?", (time.time() - 1, _token_hash(tok2)))
    assert auth.session_user(tok2) is None                   # expired


def test_change_password(auth):
    uid = auth.register("alice", PW, PW, "alice@example.com")["id"]
    keep, other = auth.create_session(uid), auth.create_session(uid)
    with pytest.raises(TradingError, match="現有密碼錯誤"):
        auth.change_password(uid, "wrong-pass", "new-password-1", "new-password-1")
    with pytest.raises(TradingError, match="唔一樣"):
        auth.change_password(uid, PW, "new-password-1", "new-password-2")
    with pytest.raises(TradingError, match="舊密碼"):
        auth.change_password(uid, PW, PW, PW)
    auth.change_password(uid, PW, "new-password-1", "new-password-1", keep_token=keep)
    assert auth.session_user(keep) and auth.session_user(other) is None
    with pytest.raises(AuthError):
        auth.authenticate("alice", PW)
    assert auth.authenticate("alice", "new-password-1")


def test_migration_removes_legacy_passwordless_users(tmp_path, feed):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)  # v1 schema (no auth columns)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                            created_at REAL NOT NULL, reset_at REAL NOT NULL);
        CREATE TABLE cash (user_id INTEGER NOT NULL, currency TEXT NOT NULL, initial REAL NOT NULL,
                           balance REAL NOT NULL, reserved REAL NOT NULL DEFAULT 0, PRIMARY KEY (user_id, currency));
        INSERT INTO users(username, created_at, reset_at) VALUES ('demo', 0, 0), ('小明', 0, 0);
        INSERT INTO cash VALUES (1, 'HKD', 1000000, 1000000, 0);
    """)
    con.commit(); con.close()
    eng = Engine(str(db), feed)
    a = AuthService(eng)
    assert sorted(a.migrate_legacy_users()) == sorted(["demo", "小明"])
    assert eng.list_users() == [] and eng.db.execute("SELECT COUNT(*) FROM cash").fetchone()[0] == 0
    a.register("demo", PW, PW, "demo@example.com")                               # name can be registered again, with a password
    assert a.migrate_legacy_users() == [] and eng.list_users() == ["demo"]


def test_concurrent_access_is_safe(tmp_path, feed):
    """Regression: the shared sqlite connection is used from many threads (FastAPI thread pool)."""
    import threading
    eng = Engine(str(tmp_path / "c.db"), feed)
    a = AuthService(eng)
    uid = a.register("alice", PW, PW, "alice@example.com")["id"]
    tok = a.create_session(uid)
    errors = []

    def reader():
        try:
            for _ in range(150):
                assert a.session_user(tok)["username"] == "alice"
                eng.portfolio("alice")
                eng.orders("alice", "PENDING")
        except Exception as e:  # pragma: no cover
            errors.append(repr(e))

    def writer():
        try:
            for _ in range(40):
                eng.place_order("alice", "AAPL", "BUY", "MARKET", 1)
                eng.place_order("alice", "AAPL", "SELL", "MARKET", 1)
        except Exception as e:  # pragma: no cover
            errors.append(repr(e))

    ts = [threading.Thread(target=reader) for _ in range(6)] + [threading.Thread(target=writer) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
    assert len(eng.trades("alice")) == 160
    assert next(x for x in eng.portfolio("alice")["accounts"] if x["currency"] == "USD")["cash"] == 100_000
