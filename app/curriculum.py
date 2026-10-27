"""Week curriculum loader + MC scoring (Week 1: fundamentals).

Lesson / MC JSON live under repo `curriculum/week1/` so Railway can serve them
from the image (Dockerfile copies `curriculum/`).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CURRICULUM_ROOT = ROOT / "curriculum"

# Active week for GET /api/curriculum/week/current
CURRENT_WEEK_ID = "week1-fundamentals"
CURRENT_WEEK_DIR = "week1"

HOLD_DAYS_REQUIRED = 7
BOOST_EQUITY_PCT = 0.01  # one-shot cash credit = 1% of total equity (USD)
WEEKLY_TOP_REWARD_USD = 1000.0  # documented prize; leaderboard is ranking-only for now


class CurriculumError(ValueError):
    """Business-rule rejection for curriculum / boost APIs."""


def _week_dir(week_id: str | None = None) -> Path:
    wid = week_id or CURRENT_WEEK_ID
    # Map weekId → folder name
    if wid in (CURRENT_WEEK_ID, "week1", CURRENT_WEEK_DIR):
        return CURRICULUM_ROOT / CURRENT_WEEK_DIR
    # Future weeks: curriculum/<week_id>/ or curriculum/weekN/
    cand = CURRICULUM_ROOT / wid
    if cand.is_dir():
        return cand
    raise CurriculumError(f"未知教材週：{wid}")


@lru_cache(maxsize=8)
def load_mc(week_id: str = CURRENT_WEEK_ID) -> dict[str, Any]:
    path = _week_dir(week_id) / "mc.json"
    if not path.is_file():
        raise CurriculumError(f"搵唔到 MC：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("weekId"):
        data["weekId"] = week_id
    return data


def load_lesson_markdown(week_id: str = CURRENT_WEEK_ID) -> str:
    path = _week_dir(week_id) / "lesson.md"
    if not path.is_file():
        raise CurriculumError(f"搵唔到課文：{path}")
    return path.read_text(encoding="utf-8")


def lesson_path_rel(week_id: str = CURRENT_WEEK_ID) -> str:
    d = _week_dir(week_id)
    return str((d / "lesson.md").relative_to(ROOT)).replace("\\", "/")


def public_questions(mc: dict[str, Any]) -> list[dict[str, Any]]:
    """Strip answer key + explain before sending to clients."""
    out = []
    for q in mc.get("questions") or []:
        out.append({
            "id": q["id"],
            "stem": q["stem"],
            "choices": [{"key": c["key"], "text": c["text"]} for c in q.get("choices") or []],
        })
    return out


def score_answers(mc: dict[str, Any], answers: dict[str, str]) -> dict[str, Any]:
    """Grade {qId: 'A'|'B'|...}. Missing / invalid → wrong."""
    questions = mc.get("questions") or []
    total = int(mc.get("total") or len(questions))
    pass_score = int(mc.get("passScore") or 5)
    score = 0
    details = []
    for q in questions:
        qid = q["id"]
        correct = (q.get("answer") or "").strip().upper()
        given = (answers.get(qid) or "").strip().upper()
        ok = bool(given) and given == correct
        if ok:
            score += 1
        details.append({"id": qid, "correct": ok, "answer": correct, "explain": q.get("explain")})
    return {
        "score": score,
        "passed": score >= pass_score,
        "total": total,
        "passScore": pass_score,
        "details": details,
    }


def universe_of(week_id: str = CURRENT_WEEK_ID) -> list[str]:
    return [str(s).upper() for s in (load_mc(week_id).get("universe") or [])]
