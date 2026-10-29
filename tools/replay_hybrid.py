"""Review hybrid decisions with closed EMAs and verified option histories; NO AI/PnL."""

import argparse
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path

from execution_safety import atomic_save
from market_clock import MarketClock
from trading.adapters.historical import load_option_history, read_workspace_json, workspace_path
from trading.application.dossier import DossierService
from trading.bootstrap import configure_console
from trading.configuration import load_configuration
from trading.domain.market_data import exchange_time
from trading.hybrid_research import HybridHistoricalReview


def review_session(session, *, root=None):
    root = Path.cwd() if root is None else Path(root)
    settings = load_configuration("macd_momentum", "rules", root=root, environ={})
    rows = read_workspace_json(f"data/spot_candles_{session.replace('-', '')}.json", root=root)
    prior = []
    for offset in range(14, 0, -1):
        previous = (date.fromisoformat(session) - timedelta(days=offset)).strftime("%Y%m%d")
        path = workspace_path(f"data/spot_candles_{previous}.json", root=root)
        if path.exists():
            prior.extend(read_workspace_json(path, root=root))
    with MarketClock.at(session + "T09:15:00+05:30"):
        days = DossierService(settings.trading).get_days_to_expiry()
        expiry = (date.fromisoformat(session) + timedelta(days=days)).isoformat()
    options = load_option_history(session, expiry, root=root)
    reviewer = HybridHistoricalReview(settings.strategy, settings.trading)
    observations = []
    entry = settings.strategy.get("entry", {})
    first = 15 if entry.get("prior_session_warmup_enabled", False) else (28 if entry.get("use_rolling_2m", False) else 54)
    cadence = 1 if entry.get("use_rolling_2m", False) else 2
    if not entry.get("use_rolling_2m", False) and first % 2:
        first += 1
    for count in range(first, len(rows) + 1, cadence):
        now = exchange_time(rows[count - 1]["start_time"]) + timedelta(minutes=1)
        if now.strftime("%H:%M") >= "14:15":
            break
        result = reviewer.evaluate(rows, now=now, expiry=expiry, options=options, prior_rows=prior)
        observations.append(dict(result, observed_at=now.isoformat()))
    return dict(session=session, evaluation_mode="rules", ai_used=False, scope="DECISION_REPLAY_ONLY",
                limitations=["No historical companion verdicts or fills", "Macro/news and executable depth unavailable",
                             "No portfolio simulation, PnL or ROI validation"],
                excluded_option_files=options.excluded_files,
                counts=dict(Counter(row["blocked"] or row["signal"] for row in observations)),
                observations=observations)


def main(argv=None):
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default=MarketClock.today_ist_str(), help="YYYY-MM-DD")
    parser.add_argument("--output", help="Workspace-local JSON report path")
    args = parser.parse_args(argv)
    try:
        date.fromisoformat(args.session)
        report = review_session(args.session)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    if args.output:
        atomic_save(workspace_path(args.output), report)
    print(json.dumps({key: value for key, value in report.items() if key != "observations"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
