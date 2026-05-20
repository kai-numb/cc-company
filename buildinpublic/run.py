"""build-in-public 日次パイプラインのエントリポイント。

使い方:
  python -m buildinpublic.run                     # 当日 (UTC) を本番投稿
  python -m buildinpublic.run --dry-run           # 投稿せずログのみ
  python -m buildinpublic.run --date 2026-05-11   # 指定日

環境変数 DRY_RUN=true でも dry-run になる (GitHub Actions vars 経由)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .collect import collect_since
from .filter import filter_items
from .log import append_log
from .summarize import generate_thread
from .x_post import PostedThread, post_thread

REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="buildinpublic")
    p.add_argument("--date", help="YYYY-MM-DD (default: today UTC)")
    p.add_argument("--dry-run", action="store_true", help="投稿しない")
    p.add_argument(
        "--hours",
        type=int,
        default=24,
        help="git log を遡る時間幅 (default: 24h)",
    )
    return p.parse_args(argv)


def _is_truthy_env(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes"}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dry_run = args.dry_run or _is_truthy_env("DRY_RUN")

    if args.date:
        target_date = date.fromisoformat(args.date)
    else:
        target_date = datetime.now(tz=timezone.utc).date()

    since = datetime(
        target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc
    ) - timedelta(hours=max(0, args.hours - 24))

    print(f"[buildinpublic] target_date={target_date} since={since.isoformat()} dry_run={dry_run}")

    items = collect_since(since=since, repo_root=REPO_ROOT, target_date=target_date)
    print(f"[buildinpublic] collected {len(items)} item(s)")

    # fail-soft: 集約 0 件なら過去 7 日まで遡って fallback (動きが薄い日も投稿継続)
    if not items:
        fallback_since = since - timedelta(days=7)
        print(f"[buildinpublic] fallback: re-collecting since {fallback_since.isoformat()} (last 7 days)")
        items = collect_since(since=fallback_since, repo_root=REPO_ROOT, target_date=target_date)
        print(f"[buildinpublic] fallback collected {len(items)} item(s)")

    filtered = filter_items(items)
    print(f"[buildinpublic] passed={filtered.passed_count} rejected={filtered.rejected_count}")
    for item, reason in filtered.rejected:
        print(f"  rejected [{item.source}] {item.title[:60]} -- {reason}")

    if filtered.passed_count == 0:
        print("[buildinpublic] nothing to post (0 passed). exit success.")
        append_log(target_date, None, [], filtered, dry_run=dry_run)
        return 0

    thread = generate_thread(filtered.passed, target_date=target_date, dry_run=dry_run)
    print(f"[buildinpublic] thread length: {len(thread)}")
    for t in thread:
        text = t.get("text", "")
        print(f"  [{t.get('index')}] {text}")

    if not thread:
        print("[buildinpublic] model returned empty thread. exit success.")
        append_log(target_date, None, [], filtered, dry_run=dry_run)
        return 0

    posted: PostedThread | None
    if dry_run:
        posted = post_thread(thread, dry_run=True)
        print(f"[buildinpublic] DRY-RUN posted preview: {posted.first_url}")
        log_path = append_log(target_date, posted, thread, filtered, dry_run=dry_run)
        print(f"[buildinpublic] log: {log_path}")
        return 0

    try:
        posted = post_thread(thread, dry_run=False)
    except Exception as e:
        # 投稿失敗時：生成済み thread を保全（手動再投稿可能に） + log に失敗記録 + workflow を red にして取締役会に通知
        # Case 20 (X API 403) の教訓：thread 生成までは成功するため、失われると同じ集約をやり直す必要が出る
        err_msg = f"{type(e).__name__}: {e}"
        print(f"[buildinpublic] POST FAILED: {err_msg}", file=sys.stderr)

        failed_thread_path = Path(__file__).parent / "logs" / f"failed-thread-{target_date.isoformat()}.json"
        failed_thread_path.parent.mkdir(parents=True, exist_ok=True)
        with failed_thread_path.open("w", encoding="utf-8") as f:
            json.dump(
                {"target_date": target_date.isoformat(), "thread": thread, "error": err_msg},
                f, ensure_ascii=False, indent=2,
            )
        print(f"[buildinpublic] failed thread saved: {failed_thread_path}", file=sys.stderr)
        append_log(target_date, None, thread, filtered, dry_run=dry_run, error=err_msg)
        raise


    print(f"[buildinpublic] POSTED: {posted.first_url}")
    log_path = append_log(target_date, posted, thread, filtered, dry_run=dry_run)
    print(f"[buildinpublic] log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
