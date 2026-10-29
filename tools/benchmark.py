"""Measure offline decision/actual-playbook-AI compute time, excluding all broker I/O."""

import argparse
import json
from statistics import median
import time

from execution_safety import atomic_save
from trading.adapters.historical import read_workspace_json, workspace_path
from trading.configuration import load_configuration
from trading.replay import ReplayService


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Workspace-local replay input")
    parser.add_argument("--strategy", default=None)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    if not 1 <= args.iterations <= 10000:
        parser.error("Iterations must be between 1 and 10000")
    records = read_workspace_json(args.input)
    if not isinstance(records, list) or not records:
        parser.error("Input must contain at least one replay record")
    replay = ReplayService(load_configuration(args.strategy, "playbook"))
    elapsed, approved, vetoed = [], 0, 0
    for index in range(args.iterations):
        record = records[index % len(records)]
        started = time.perf_counter()
        result = replay.evaluate(
            record["context"],
            record["intelligence"],
            now=record["now"],
            history=record.get("history", ()),
            today_entries=record.get("today_entries", 0),
        )
        elapsed.append((time.perf_counter() - started) * 1000)
        verdict = result["verdict"] or {}
        approved += verdict.get("action") == "APPROVED"
        vetoed += verdict.get("action") == "VETOED"
    ordered = sorted(elapsed)
    report = dict(
        scope="offline decision and actual playbook AI; no broker/network latency",
        iterations=args.iterations,
        approved=approved,
        vetoed=vetoed,
        median_ms=median(elapsed),
        p95_ms=ordered[int((len(ordered) - 1) * 0.95)],
        p99_ms=ordered[int((len(ordered) - 1) * 0.99)],
        max_ms=max(elapsed),
    )
    if args.output:
        atomic_save(workspace_path(args.output), report)
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
