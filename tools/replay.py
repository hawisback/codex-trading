"""Evaluate workspace-local recorded contexts through the actual live decision policies."""

import argparse
import json

from execution_safety import atomic_save
from trading.adapters.historical import read_workspace_json, workspace_path
from trading.configuration import load_configuration
from trading.replay import ReplayService
from trading.bootstrap import configure_console


def main(argv=None):
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Workspace-local JSON list of context/intelligence/now records")
    parser.add_argument("--strategy", default=None)
    parser.add_argument("--output", default=None, help="Optional workspace-local JSON report")
    args = parser.parse_args(argv)
    records = read_workspace_json(args.input)
    if not isinstance(records, list):
        parser.error("Replay input must be a list")
    replay = ReplayService(load_configuration(args.strategy, "playbook"))
    result = [
        replay.evaluate(
            row["context"],
            row["intelligence"],
            now=row["now"],
            history=row.get("history", ()),
            today_entries=row.get("today_entries", 0),
        )
        for row in records
    ]
    if args.output:
        atomic_save(workspace_path(args.output), {"evaluations": result})
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
