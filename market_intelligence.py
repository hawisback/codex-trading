#!/usr/bin/env python3
"""
Market Intelligence Connector for NIFTY Options
Ingests real-time external catalysts:
1. Global Intermarket Cues (Crude Oil, Dow, Nasdaq, USD/INR)
2. Live Indian Financial News (Moneycontrol and Economic Times)
3. Financial Sentiment Analysis & Trap Divergence Warnings
"""

import time
import copy
import math
import os
import sys
import tempfile
import threading
import json
import logging
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from market_clock import MarketClock
from execution_safety import atomic_save
from pathlib import Path
from typing import Dict, List, Any

logger = logging.getLogger("MarketIntelligence")

# Bullish / Bearish financial lexicon tuned for Indian stock market & NIFTY
BULLISH_KEYWORDS = {
    "surge", "surges", "surging", "soar", "soars", "rally", "rallies", "gain", "gains",
    "profit jumps", "beats estimates", "strong results", "rate cut", "inflows",
    "all-time high", "record high", "bullish", "upgrade", "outperform", "rebound",
    "buying spree", "gdp beats", "inflation cools", "crude drops", "fii buying"
}

BEARISH_KEYWORDS = {
    "slump", "slumps", "crash", "crashes", "fall", "falls", "falling", "plunge", "plunges",
    "loss widens", "misses estimates", "weak results", "rate hike", "outflows",
    "fii selling", "bearish", "downgrade", "underperform", "selloff", "bloodbath",
    "inflation spikes", "crude surges", "oil surges", "deficit widens", "geopolitical tension",
    "war", "escalation", "recession fears"
}

HEAVYWEIGHTS = [
    "HDFC", "RELIANCE", "ICICI", "INFOSYS", "TCS", "SBI", "L&T", "KOTAK", "AXIS", "ITC"
]


class MarketIntelligence:
    QUOTES = {
        "CL=F": ("Brent/Crude", "COMMODITY"),
        "^DJI": ("Dow Jones", "US_EQUITY"),
        "^IXIC": ("Nasdaq", "US_TECH"),
        "INR=X": ("USD/INR", "CURRENCY"),
        "NSEIX:NIFTY1!": ("GIFT Nifty", "OFFSHORE_INDEX"),
    }
    FEEDS = {
        "Moneycontrol Top News": "https://www.moneycontrol.com/rss/MCtopnews.xml",
        "ET Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    }
    MAX_RESPONSE_BYTES = 1_000_000

    def __init__(self, cache_ttl_seconds: int = 120, *, refresh_interval_seconds: float = 60,
                 start_worker: bool = True, snapshot_dir=None):
        if not math.isfinite(cache_ttl_seconds) or cache_ttl_seconds <= 0:
            raise ValueError("Cache freshness TTL must be positive")
        if not math.isfinite(refresh_interval_seconds) or refresh_interval_seconds <= 0:
            raise ValueError("Refresh interval must be positive")
        self.cache_ttl = cache_ttl_seconds
        self.refresh_interval = refresh_interval_seconds
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir is not None else Path(__file__).resolve().parent / "logs"
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker = None
        self._generation = 0
        self._latest_spot_change = 0.0
        self._refreshing = False
        self._last_refresh_started_at = None
        self._last_refresh_duration = None
        self._last_refresh_error = None
        # Worker-owned state; published snapshots are independent, immutable-by-convention copies.
        self._sources = {name: {"data": None, "last_success_at": None, "success_monotonic": None,
                               "last_attempt_at": None, "error": None}
                         for name in [v[0] for v in self.QUOTES.values()] + list(self.FEEDS)}
        self._cached_data = {"timestamp": None, "sources": copy.deepcopy(self._sources)}
        if start_worker:
            self.start_worker()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop_worker()

    def start_worker(self):
        with self._lifecycle_lock:
            if self._stop_event.is_set():
                raise RuntimeError("A stopped intelligence worker cannot be restarted")
            if self._worker is not None:
                return
            self._worker = threading.Thread(target=self._worker_loop, name="MarketIntelligence", daemon=True)
            self._worker.start()

    def stop_worker(self, timeout=1.0):
        """Idempotent, bounded teardown; an in-flight socket call cannot be forcibly interrupted."""
        self._stop_event.set()
        with self._changed:
            self._changed.notify_all()
        with self._lifecycle_lock:
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=max(0, timeout))
        return worker is None or not worker.is_alive()

    def wait_until_ready(self, timeout=30.0):
        """Explicit bounded wait for reporting commands only. Trading never waits here."""
        deadline = time.monotonic() + max(0, timeout)
        while not self._stop_event.is_set():
            with self._lock:
                generation = self._generation
            if self._snapshot(0, remember_spot=False)["ready"]:
                return True
            with self._changed:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                if generation == self._generation and not self._stop_event.is_set():
                    self._changed.wait(left)
        return False

    def _read_payload(self, url):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        data = None
        if "scanner.tradingview.com" in url:
            headers["Content-Type"] = "application/json"
            data = json.dumps({
                "symbols": {"tickers": ["NSEIX:NIFTY1!"]},
                "columns": ["close", "change", "description", "open", "high", "low", "volume"]
            }).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=4) as response:
            payload = response.read(self.MAX_RESPONSE_BYTES + 1)
        if len(payload) > self.MAX_RESPONSE_BYTES:
            raise ValueError("Intelligence response exceeds size limit")
        return payload

    @staticmethod
    def _global_summary(items):
        score = 0
        for item in items.values():
            change = item.get("change_pct", 0)
            category = item.get("category")
            if category == "COMMODITY":
                score += -1 if change > 1.5 else (1 if change < -1.5 else 0)
            elif category == "CURRENCY":
                score += -1 if change > .4 else (1 if change < -.4 else 0)
            elif category in ("US_EQUITY", "US_TECH"):
                score += 1 if change > .4 else (-1 if change < -.4 else 0)
            elif category == "OFFSHORE_INDEX":
                score += 1 if change > .3 else (-1 if change < -.3 else 0)
        bias = "STRONGLY_BULLISH" if score >= 2 else "MILDLY_BULLISH" if score == 1 else "STRONGLY_BEARISH" if score <= -2 else "MILDLY_BEARISH" if score == -1 else "NEUTRAL"
        return {"items": items, "global_bias": bias, "score": score}

    @staticmethod
    def _news_summary(feeds):
        headlines = [h for feed in feeds for h in feed.get("headlines", [])]
        catalysts = [c for feed in feeds for c in feed.get("catalysts", [])]
        score = sum(feed.get("sentiment_score", 0) for feed in feeds)
        return {"total_headlines": len(headlines), "sentiment_score": score,
                "news_bias": "BULLISH" if score >= 3 else "BEARISH" if score <= -3 else "NEUTRAL",
                "catalysts": catalysts[:5], "headlines": headlines[:10]}

    def fetch_global_cues(self) -> Dict[str, Any]:
        """Network work, invoked by the background worker, never by the getter."""
        results = {}
        for symbol, (label, category) in self.QUOTES.items():
            if self._stop_event.is_set():
                break
            try:
                if category == "OFFSHORE_INDEX":
                    raw = json.loads(self._read_payload("https://scanner.tradingview.com/futures/scan"))
                    row = raw["data"][0]["d"]
                    price = float(row[0])
                    change_pct = float(row[1])
                    if not math.isfinite(price) or price <= 0 or not math.isfinite(change_pct):
                        raise ValueError("Invalid quote price/change")
                    results[label] = {
                        "symbol": symbol,
                        "category": category,
                        "price": price,
                        "change_pct": round(change_pct, 2),
                        "market_timestamp": None,
                        "fetched_at": MarketClock.now_ist().isoformat(),
                        "_fetched_monotonic": time.monotonic(),
                    }
                    continue

                encoded = urllib.parse.quote(symbol, safe="")
                data = json.loads(self._read_payload(f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range=1d"))
                meta = data["chart"]["result"][0]["meta"]
                price, previous = float(meta["regularMarketPrice"]), float(meta.get("previousClose", meta.get("chartPreviousClose")))
                if not math.isfinite(price) or not math.isfinite(previous) or price <= 0 or previous <= 0:
                    raise ValueError("Invalid quote price/previous close")
                results[label] = {"symbol": symbol, "category": category, "price": price,
                                  "change_pct": round((price - previous) / previous * 100, 2),
                                  "market_timestamp": meta.get("regularMarketTime"),
                                  "fetched_at": MarketClock.now_ist().isoformat(),
                                  "_fetched_monotonic": time.monotonic()}
            except Exception as exc:
                results[label] = {"error": str(exc) or type(exc).__name__}
        return self._global_summary(results)

    def fetch_news_feed(self) -> Dict[str, Any]:
        sources = {}
        for name, url in self.FEEDS.items():
            if self._stop_event.is_set():
                break
            try:
                root = ET.fromstring(self._read_payload(url))
                if root.find("channel") is None:
                    raise ValueError("Response is not an RSS channel")
                headlines, catalysts, score = [], [], 0
                for item in root.findall("./channel/item")[:12]:
                    title = (item.findtext("title") or "").strip()[:2048]
                    if not title:
                        continue
                    lower = title.lower()
                    bulls = [word for word in BULLISH_KEYWORDS if word in lower]
                    bears = [word for word in BEARISH_KEYWORDS if word in lower]
                    delta = 1 if len(bulls) > len(bears) else -1 if len(bears) > len(bulls) else 0
                    sentiment = "BULLISH" if delta > 0 else "BEARISH" if delta < 0 else "NEUTRAL"
                    score += delta
                    tags = [word for word in HEAVYWEIGHTS if word.lower() in lower]
                    if (bulls or bears) and (tags or any(word in lower for word in ("nifty", "rbi", "fed"))):
                        catalysts.append({"title": title, "sentiment": sentiment, "source": name, "tags": tags or ["MACRO"]})
                    headlines.append({"title": title, "sentiment": sentiment, "source": name,
                                      "published": item.findtext("pubDate"),
                                      "link": (item.findtext("link") or "")[:2048], "heavyweights": tags})
                if not headlines:
                    raise ValueError("RSS contains no usable headlines")
                sources[name] = {"headlines": headlines, "catalysts": catalysts, "sentiment_score": score,
                                 "fetched_at": MarketClock.now_ist().isoformat(), "_fetched_monotonic": time.monotonic()}
            except Exception as exc:
                sources[name] = {"error": str(exc) or type(exc).__name__}
        result = self._news_summary([v for v in sources.values() if "error" not in v])
        result["sources"] = sources
        return result

    def _refresh_once(self):
        """Single-writer refresh. Each source retains its own last successful value."""
        try:
            quotes = self.fetch_global_cues()["items"]
        except Exception as exc:
            quotes = {label: {"error": str(exc) or type(exc).__name__} for label, _ in self.QUOTES.values()}
        try:
            news = self.fetch_news_feed()["sources"]
        except Exception as exc:
            news = {name: {"error": str(exc) or type(exc).__name__} for name in self.FEEDS}
        if self._stop_event.is_set():
            return
        errors = []
        for name, record in self._sources.items():
            incoming = copy.deepcopy(quotes.get(name) if name in quotes else news.get(name))
            record["last_attempt_at"] = MarketClock.now_ist().isoformat()
            if not incoming or "error" in incoming:
                record["error"] = incoming.get("error", "Missing source result") if incoming else "Missing source result"
                errors.append(name)
            else:
                record["last_success_at"] = incoming.pop("fetched_at", record["last_attempt_at"])
                record["success_monotonic"] = incoming.pop("_fetched_monotonic", time.monotonic())
                record["data"] = incoming
                record["error"] = None
        published = {"timestamp": MarketClock.now_ist().isoformat(), "sources": copy.deepcopy(self._sources)}
        with self._changed:
            self._cached_data = published
            self._generation += 1
            self._last_refresh_error = ", ".join(errors) or None
            self._changed.notify_all()

    def _worker_loop(self):
        while not self._stop_event.is_set():
            started = time.monotonic()
            with self._lock:
                self._refreshing = True
                self._last_refresh_started_at = MarketClock.now_ist().isoformat()
            try:
                self._refresh_once()
                if not self._stop_event.is_set():
                    with self._lock:
                        spot = self._latest_spot_change
                    self.save_snapshot(self.snapshot_dir, self._snapshot(spot, remember_spot=False))
            except Exception as exc:
                with self._changed:
                    self._last_refresh_error = str(exc)
                    self._changed.notify_all()
                logger.warning("Background intelligence refresh/persistence failed: %s", exc)
            finally:
                duration = time.monotonic() - started
                with self._lock:
                    self._refreshing = False
                    self._last_refresh_duration = duration
            # Skip missed refresh periods; never queue overlapping or catch-up jobs.
            periods = max(1, math.floor(duration / self.refresh_interval) + 1)
            self._stop_event.wait(max(0, started + periods * self.refresh_interval - time.monotonic()))

    def evaluate_traps(self, global_cues: dict, news_data: dict, spot_change_pct: float) -> List[str]:
        """
        Analyze whether price movement contradicts macro/news cues (Trap Detection).
        """
        advisories = []
        global_bias = global_cues.get("global_bias", "NEUTRAL")
        news_bias = news_data.get("news_bias", "NEUTRAL")

        # 1. Bear Trap Detection
        # Global cues & news are neutral or bullish, but NIFTY is flushing down > 0.8%
        if spot_change_pct < -0.6 and global_bias in ["MILDLY_BULLISH", "STRONGLY_BULLISH", "NEUTRAL"]:
            advisories.append(
                f"POTENTIAL_BEAR_TRAP: Nifty down {spot_change_pct:.2f}% despite supportive/neutral global cues ({global_bias}). Watch for sharp short squeeze if key support holds."
            )

        # 2. Bull Trap Detection
        # Global cues or news are negative (crude spike / US selloff), but NIFTY is attempting to rally into resistance
        if spot_change_pct > 0.4 and (global_bias in ["STRONGLY_BEARISH", "MILDLY_BEARISH"] or news_bias == "BEARISH"):
            advisories.append(
                f"POTENTIAL_BULL_TRAP: Nifty up {spot_change_pct:.2f}% into adverse macro cues ({global_bias}, News: {news_bias}). High risk of long liquidation trap at resistance."
            )

        # 3. Trend Alignment
        if spot_change_pct > 0.5 and global_bias in ["MILDLY_BULLISH", "STRONGLY_BULLISH"] and news_bias != "BEARISH":
            advisories.append("HIGH_CONVICTION_BULLISH: Price action fully supported by global & news flows.")
        elif spot_change_pct < -0.5 and global_bias in ["MILDLY_BEARISH", "STRONGLY_BEARISH"] and news_bias != "BULLISH":
            advisories.append("HIGH_CONVICTION_BEARISH: Price action confirmed by macro selling pressure.")

        return advisories

    def get_market_intelligence(self, spot_change_pct: float = 0.0) -> Dict[str, Any]:
        """Memory-only snapshot read. No network, disk, sleep or readiness wait."""
        return self._snapshot(spot_change_pct)

    def _snapshot(self, spot_change_pct, *, remember_spot=True):
        spot = float(spot_change_pct)
        with self._lock:
            published = self._cached_data
            generation = self._generation
            if remember_spot:
                self._latest_spot_change = spot
            health = {"refreshing": self._refreshing, "last_refresh_started_at": self._last_refresh_started_at,
                      "last_refresh_duration_sec": self._last_refresh_duration, "last_error": self._last_refresh_error}
        # The published object is never mutated after publication, so copying need not hold the lock.
        source_records = copy.deepcopy(published["sources"])
        now = time.monotonic()
        sources, quote_data, fresh_news, retained_news = {}, {}, [], []
        quote_names = [v[0] for v in self.QUOTES.values()]
        for name, record in source_records.items():
            successful = record.pop("success_monotonic")
            data = record.pop("data")
            age = max(0, now - successful) if successful is not None else None
            fresh = data is not None and age is not None and age <= self.cache_ttl
            sources[name] = dict(record, age_seconds=age, fresh=fresh, available=data is not None)
            if name in quote_names:
                quote_data[name] = data or {"price": None, "change_pct": 0.0}
            elif data:
                retained_news.append(data)
                if fresh:
                    fresh_news.append(data)
        core_quote_names = [v[0] for k, v in self.QUOTES.items() if v[1] != "OFFSHORE_INDEX"]
        quotes_ready = all(sources[name]["fresh"] for name in core_quote_names)
        worker_alive = self._worker is not None and self._worker.is_alive()
        ready = quotes_ready and bool(fresh_news) and not self._stop_event.is_set() and math.isfinite(spot)
        if self._worker is not None and not worker_alive:
            ready = False
        partial = any(not item["fresh"] or item["error"] for item in sources.values())
        state = ("PARTIAL" if partial else "FRESH") if ready else "INITIALIZING" if not generation else "STALE" if any(item["available"] for item in sources.values()) else "UNAVAILABLE"
        if self._stop_event.is_set():
            state = "STOPPED"
        global_cues = self._global_summary(quote_data)
        news = self._news_summary(fresh_news or retained_news)
        combined = global_cues["score"] * .6 + news["sentiment_score"] * .4
        advisories = self.evaluate_traps(global_cues, news, spot) if ready else ["INTELLIGENCE_UNAVAILABLE: Required macro/news context is not fresh; new entries blocked."]
        if ready and partial:
            advisories.insert(0, "INTELLIGENCE_PARTIAL: Some sources failed or expired; consult source health and retained-data ages.")
        return {"timestamp": published["timestamp"], "generation": generation, "ready": ready, "status": state,
                "composite_bias": "BULLISH" if combined >= 1.5 else "BEARISH" if combined <= -1.5 else "NEUTRAL",
                "composite_score": round(combined, 2), "global_cues": global_cues, "news": news,
                "trap_advisories": advisories, "sources": sources,
                "worker": dict(health, alive=worker_alive, stopped=self._stop_event.is_set())}

    def format_markdown(self, intel: Dict[str, Any]) -> str:
        """Render a readable markdown summary of current market intelligence."""
        ts = intel.get("timestamp", datetime.now().isoformat())
        bias = intel.get("composite_bias", "NEUTRAL")
        score = intel.get("composite_score", 0.0)

        md = []
        md.append("# Live Market Intelligence & Macro Sentiment")
        md.append(f"**Availability**: `{intel.get('status', 'UNKNOWN')}` | **Ready for entries**: `{intel.get('ready', False)}`")
        md.append(f"**Last Updated**: `{ts}` | **Composite Bias**: **{bias}** (Score: {score:+.2f})\n")

        md.append("## 1. Global Intermarket Cues")
        gc = intel.get("global_cues", {})
        md.append(f"- **Global Bias**: `{gc.get('global_bias', 'NEUTRAL')}` (Net Score: {gc.get('score', 0):+d})")
        for name, item in gc.get("items", {}).items():
            price = item.get("price")
            chg = item.get("change_pct", 0.0)
            sign = "+" if chg > 0 else ""
            md.append(f"- **{name}**: `{price}` ({sign}{chg:.2f}%)")
        md.append("")

        md.append("## 2. Live Indian Financial News (Moneycontrol / ET Markets)")
        nd = intel.get("news", {})
        md.append(f"- **News Bias**: `{nd.get('news_bias', 'NEUTRAL')}` (Sentiment Score: {nd.get('sentiment_score', 0):+d})")
        md.append(f"- **Headlines Analyzed**: {nd.get('total_headlines', 0)}")
        cats = nd.get("catalysts", [])
        if cats:
            md.append("\n### High-Impact Catalysts")
            for c in cats[:5]:
                md.append(f"- **[{c['sentiment']}]** {c['title']} *({c.get('source', 'RSS')})*")

        hdls = nd.get("headlines", [])
        if hdls:
            md.append("\n### Recent Headlines")
            for h in hdls[:7]:
                md.append(f"- {h['title']} *({h.get('source', 'RSS')})*")
        md.append("")

        advisories = intel.get("trap_advisories", [])
        if advisories:
            md.append("## 3. Trap & Divergence Advisories")
            for adv in advisories:
                md.append(f"> ⚠️ **WARNING**: {adv}")
            md.append("")
        else:
            md.append("## 3. Trap & Divergence Advisories")
            md.append("No active macro-price trap divergences detected.\n")

        return "\n".join(md)

    def save_snapshot(self, output_dir: Path, intel: Dict[str, Any] = None) -> None:
        """Save latest intelligence snapshot as JSON and Markdown in output_dir."""
        if intel is None:
            with self._lock:
                spot = self._latest_spot_change
            intel = self._snapshot(spot, remember_spot=False)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_save(output_dir / "latest_intelligence.json", intel)
        fd, temporary = tempfile.mkstemp(prefix="latest_intelligence.", suffix=".tmp", dir=output_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(self.format_markdown(intel))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, output_dir / "latest_intelligence.md")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)




def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with MarketIntelligence() as intelligence:
        if not intelligence.wait_until_ready(timeout=30):
            print("Market intelligence unavailable: startup refresh did not produce fresh required sources.")
            print(intelligence.format_markdown(intelligence.get_market_intelligence()))
            return 1
        print(intelligence.format_markdown(intelligence.get_market_intelligence(spot_change_pct=-1.60)))
    return 0


if __name__ == "__main__":
    from trading.bootstrap import configure_console
    configure_console()
    sys.exit(main())
