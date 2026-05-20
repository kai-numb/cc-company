"""投稿ログを JSONL で日次ファイルに追記する。"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

from .filter import FilterResult
from .x_post import PostedThread

LOG_DIR = Path(__file__).parent / "logs"


def append_log(
    target_date: date,
    posted: PostedThread | None,
    thread: list[dict],
    filter_result: FilterResult,
    *,
    dry_run: bool,
    error: str | None = None,
) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{target_date.isoformat()}.jsonl"
    record = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "target_date": target_date.isoformat(),
        "dry_run": dry_run,
        "passed_count": filter_result.passed_count,
        "rejected_count": filter_result.rejected_count,
        "rejected_reasons": [reason for _, reason in filter_result.rejected],
        "thread": thread,
        "posted": (
            {
                "first_tweet_id": posted.first_tweet_id,
                "first_url": posted.first_url,
                "all_tweet_ids": posted.all_tweet_ids,
            }
            if posted
            else None
        ),
        "error": error,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


__all__ = ["append_log", "LOG_DIR"]
