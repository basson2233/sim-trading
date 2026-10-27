"""Curriculum loader + MC scoring (fundamentals bank, random draw).

Lesson / MC bank live under repo `curriculum/fundamentals/` so Railway can
serve them from the image (Dockerfile copies `curriculum/`).

Internal module key `week1-fundamentals` is kept for compliance / boost DB rows;
user-facing title / lesson do not say "Week 1".
"""
from __future__ import annotations

import json
import re
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CURRICULUM_ROOT = ROOT / "curriculum"

# Internal key for compliance / boost / attempts (stable; not a user-facing label)
CURRENT_WEEK_ID = "week1-fundamentals"
CURRENT_MODULE_DIR = "fundamentals"
MC_BANK_FILENAME = "mc_bank.json"
LESSON_FILENAME = "lesson.md"

HOLD_DAYS_REQUIRED = 7
BOOST_EQUITY_PCT = 0.01  # one-shot cash credit = 1% of total equity (USD)
WEEKLY_TOP_REWARD_USD = 1000.0  # documented prize; leaderboard is ranking-only for now

_PUBLIC_TITLE = "基本面選股入門"
_WEEK_HEADING_RE = re.compile(r"^#\s*Week\s*1\b.*$", re.IGNORECASE)


class CurriculumError(ValueError):
    """Business-rule rejection for curriculum / boost APIs."""


def _module_dir(week_id: str | None = None) -> Path:
    wid = week_id or CURRENT_WEEK_ID
    if wid in (
        CURRENT_WEEK_ID,
        "week1",
        "fundamentals",
        "fundamentals-basics",
        CURRENT_MODULE_DIR,
    ):
        path = CURRICULUM_ROOT / CURRENT_MODULE_DIR
        if path.is_dir():
            return path
    cand = CURRICULUM_ROOT / wid
    if cand.is_dir():
        return cand
    legacy = CURRICULUM_ROOT / "week1"
    if legacy.is_dir():
        return legacy
    raise CurriculumError(f"未知教材模組：{wid}")


@lru_cache(maxsize=8)
def load_mc(week_id: str = CURRENT_WEEK_ID) -> dict[str, Any]:
    d = _module_dir(week_id)
    data = None
    for name in (MC_BANK_FILENAME, "mc.json"):
        path = d / name
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            break
    if data is None:
        raise CurriculumError(f"搵唔到 MC bank：{d}")

    # Keep stable internal key for compliance/boost rows
    aliases = {
        CURRENT_WEEK_ID,
        "week1",
        "fundamentals",
        "fundamentals-basics",
        CURRENT_MODULE_DIR,
    }
    data["weekId"] = CURRENT_WEEK_ID if week_id in aliases else (data.get("weekId") or week_id)
    if not data.get("title"):
        data["title"] = _PUBLIC_TITLE
    questions = data.get("questions") or []
    data["drawCount"] = int(data.get("drawCount") or 7)
    data["passScore"] = int(data.get("passScore") or 5)
    data["total"] = int(data["drawCount"])  # served quiz length, not bank size
    data["bankSize"] = len(questions)
    return data


def sanitize_lesson_markdown(text: str, title: str = _PUBLIC_TITLE) -> str:
    """Remove user-facing Week 1 labels from served lesson markdown."""
    lines = text.splitlines()
    if lines and _WEEK_HEADING_RE.match(lines[0]):
        lines[0] = f"# 課文：{title}"
    return "\n".join(lines)


def load_lesson_markdown(week_id: str = CURRENT_WEEK_ID) -> str:
    d = _module_dir(week_id)
    path = d / LESSON_FILENAME
    if not path.is_file():
        path = d / "lesson.md"
    if not path.is_file():
        raise CurriculumError(f"搵唔到課文：{path}")
    return sanitize_lesson_markdown(path.read_text(encoding="utf-8"), title=_PUBLIC_TITLE)


def lesson_path_rel(week_id: str = CURRENT_WEEK_ID) -> str:
    d = _module_dir(week_id)
    for name in (LESSON_FILENAME, "lesson.md"):
        p = d / name
        if p.is_file():
            return str(p.relative_to(ROOT)).replace("\\", "/")
    return str((d / LESSON_FILENAME).relative_to(ROOT)).replace("\\", "/")


def public_title(mc: dict[str, Any] | None = None) -> str:
    title = (mc or {}).get("title") or _PUBLIC_TITLE
    title = re.sub(r"^Week\s*1\s*[·:：\-]?\s*", "", str(title), flags=re.IGNORECASE).strip()
    return title or _PUBLIC_TITLE


def public_questions(questions: list[dict[str, Any]] | dict[str, Any]) -> list[dict[str, Any]]:
    """Strip answer key + explain before sending to clients.

    Accepts either a list of question dicts or a legacy mc dict with `questions`.
    """
    if isinstance(questions, dict):
        questions = questions.get("questions") or []
    out = []
    for q in questions or []:
        out.append({
            "id": q["id"],
            "stem": q["stem"],
            "choices": [{"key": c["key"], "text": c["text"]} for c in q.get("choices") or []],
        })
    return out


def draw_questions(mc: dict[str, Any]) -> list[dict[str, Any]]:
    """Randomly draw `drawCount` questions from the bank (order randomized)."""
    bank = list(mc.get("questions") or [])
    n = min(int(mc.get("drawCount") or 7), len(bank))
    if n <= 0:
        return []
    return secrets.SystemRandom().sample(bank, n)


def score_answers(mc: dict[str, Any], answers: dict[str, str]) -> dict[str, Any]:
    """Grade by question id against the full bank.

    `total` / pass line use drawCount (served quiz size), not bank size.
    At most `drawCount` answer keys are accepted; extras → CurriculumError.
    """
    bank = {q["id"]: q for q in (mc.get("questions") or [])}
    draw_count = int(mc.get("drawCount") or mc.get("total") or 7)
    pass_score = int(mc.get("passScore") or 5)

    cleaned: dict[str, str] = {}
    for k, v in (answers or {}).items():
        qid = str(k)
        if qid in bank:
            cleaned[qid] = str(v).strip().upper()
    if len(cleaned) > draw_count:
        raise CurriculumError(f"答題數不可超過 {draw_count} 題")

    score = 0
    details = []
    for qid, given in cleaned.items():
        q = bank[qid]
        correct = (q.get("answer") or "").strip().upper()
        ok = bool(given) and given == correct
        if ok:
            score += 1
        details.append({
            "id": qid,
            "correct": ok,
            "answer": correct,
            "explain": q.get("explain"),
        })
    return {
        "score": score,
        "passed": score >= pass_score,
        "total": draw_count,
        "passScore": pass_score,
        "details": details,
    }


def universe_of(week_id: str = CURRENT_WEEK_ID) -> list[str]:
    return [str(s).upper() for s in (load_mc(week_id).get("universe") or [])]
