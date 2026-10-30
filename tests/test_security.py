"""Hardening: no openapi, no static answer keys, security headers, admin gate."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app, ROOT

PW = "secret-pass-1"
ADMIN_KEY = "test-admin-key-please-change"
STATIC_CURRICULUM = ROOT / "static" / "curriculum"


@pytest.fixture
def app(feed, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    return create_app(db_path=":memory:", feed=feed, pending_interval=0)


@pytest.fixture
def app_no_admin(feed, monkeypatch):
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.setenv("ADMIN_API_KEY", "")
    return create_app(db_path=":memory:", feed=feed, pending_interval=0)


def client(app):
    return TestClient(app, follow_redirects=False)


def test_openapi_disabled(app):
    c = client(app)
    assert c.get("/openapi.json").status_code == 404
    assert c.get("/docs").status_code == 404
    assert c.get("/redoc").status_code == 404


def test_security_headers_on_health(app):
    c = client(app)
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "geolocation=()" in (r.headers.get("Permissions-Policy") or "")
    csp = r.headers.get("Content-Security-Policy") or ""
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_static_mc_json_has_no_answers(app):
    """Public static curriculum must not leak answer / explain keys."""
    c = client(app)
    paths = [
        "/static/curriculum/mc_bank_fundamentals.json",
        "/static/curriculum/fundamentals/mc_bank.json",
        "/static/curriculum/week1/mc.json",
    ]
    for path in paths:
        r = c.get(path)
        assert r.status_code == 200, path
        data = r.json()
        for q in data.get("questions") or []:
            assert "answer" not in q, path
            assert "explain" not in q, path
            assert "stem" in q and "choices" in q


def test_repo_static_mc_files_stripped():
    """Source tree under static/curriculum must not contain answer keys."""
    assert STATIC_CURRICULUM.is_dir()
    found = list(STATIC_CURRICULUM.rglob("*.json"))
    assert found, "expected static curriculum JSON files"
    for path in found:
        data = json.loads(path.read_text(encoding="utf-8"))
        for q in data.get("questions") or []:
            assert "answer" not in q, path
            assert "explain" not in q, path


def test_private_curriculum_bank_still_has_answers():
    priv = ROOT / "curriculum" / "fundamentals" / "mc_bank.json"
    data = json.loads(priv.read_text(encoding="utf-8"))
    assert data.get("questions")
    assert all("answer" in q for q in data["questions"])


def test_admin_page_404_without_key(app_no_admin):
    c = client(app_no_admin)
    assert c.get("/admin").status_code == 404


def test_admin_page_ok_with_key_and_noindex(app):
    c = client(app)
    r = c.get("/admin")
    assert r.status_code == 200
    assert "noindex" in (r.headers.get("X-Robots-Tag") or "")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
