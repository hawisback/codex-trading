"""Offline daily report rebuilding and optional compression of old runtime logs."""

import argparse
from datetime import date, datetime, timedelta
import gzip
import json
import os
import re
import shutil
import tempfile

from execution_safety import SchedulerLock
from market_clock import IST_TZ
from trading.adapters.daily_logs import rebuild_reports
from trading.adapters.historical import workspace_path


def compress_runtime_logs(directory, older_than_days, *, today=None):
    if older_than_days < 1:
        raise ValueError("Retention age must be at least one day")
    today = today or datetime.now(IST_TZ).date()
    cutoff = today - timedelta(days=older_than_days)
    result = []
    directory = workspace_path(directory)
    for path in sorted(directory.glob("trader-????-??-??.log")):
        if not re.fullmatch(r"trader-\d{4}-\d{2}-\d{2}\.log", path.name):
            continue
        try:
            day = date.fromisoformat(path.name[7:-4])
        except ValueError:
            continue
        if day >= cutoff:
            continue
        workspace_path(path, root=directory)
        destination = path.with_suffix(".log.gz")
        if destination.exists():
            raise FileExistsError(f"Archive already exists; original retained: {destination.name}")
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as target, path.open("rb") as source:
                with gzip.GzipFile(filename="", mode="wb", fileobj=target) as archive:
                    shutil.copyfileobj(source, archive)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, destination)
            path.unlink()
            result.append(destination.name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default="logs", help="Workspace-local log directory")
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="Rebuild CSV and summary from a day's journal")
    report.add_argument("date", type=date.fromisoformat, help="IST date YYYY-MM-DD")
    compress = commands.add_parser("compress", help="Compress older dated runtime logs; keep journals")
    compress.add_argument("--older-than-days", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        directory = workspace_path(args.directory)
        if not directory.is_dir():
            parser.error("Log directory does not exist")
        # Never rewrite a report or compress a runtime file held by a live scheduler.
        with SchedulerLock(directory / "scheduler.lock"):
            if args.command == "report":
                summary = rebuild_reports(
                    workspace_path(directory / "daily" / args.date.isoformat(), root=directory)
                )
                print(json.dumps(summary, indent=2))
            else:
                print(json.dumps(compress_runtime_logs(directory, args.older_than_days), indent=2))
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
