import json
from pathlib import Path

consults = json.load(open("logs/backtest_audit/consultations_30_sessions.json", "r", encoding="utf-8"))
trades = json.load(open("logs/backtest_audit/trades_30_sessions.json", "r", encoding="utf-8"))

artifact_path = Path(r"C:\Users\hawis\.gemini\antigravity\brain\12b9612f-02ad-41a8-a4e7-6c03a05bf7fb\backtest_30_sessions_ai_report.md")

latencies = [c["latency_ms"] for c in consults if c.get("latency_ms") is not None]
min_lat = min(latencies) if latencies else 0.0
max_lat = max(latencies) if latencies else 0.0
mean_lat = sum(latencies)/len(latencies) if latencies else 0.0
sorted_lat = sorted(latencies)
median_lat = sorted_lat[len(sorted_lat)//2] if sorted_lat else 0.0
p95_lat = sorted_lat[int(len(sorted_lat)*0.95)] if sorted_lat else 0.0

total_c = len(consults)
approved = sum(1 for c in consults if c["verdict"] == "APPROVED")
vetoed = sum(1 for c in consults if c["verdict"] == "VETOED")

wins = [t for t in trades if t["pnl_pts"] > 0]
losses = [t for t in trades if t["pnl_pts"] <= 0]
win_rate = len(wins)/len(trades)*100 if trades else 0.0
net_1lot = sum(t["pnl_1lot"] for t in trades)
net_2lots = sum(t["pnl_2lots"] for t in trades)
net_comp = sum(t["pnl_compounding"] for t in trades)
gross_win = sum(t["pnl_1lot"] + 40 for t in wins)
gross_loss = abs(sum(t["pnl_1lot"] + 40 for t in losses))
pf = gross_win / gross_loss if gross_loss > 0 else 0.0

traps = {}
for c in consults:
    if c["verdict"] == "VETOED":
        t = c.get("trap_detected", "Unknown").split("(")[0].strip()
        traps[t] = traps.get(t, 0) + 1

md = []
md.append("# 📊 Comprehensive 30-Session Production Backtest: Strategy 5 (2m MACD Momentum)")
md.append("**Testing Period:** September 11, 2026 – October 27, 2026 (30 Verified Trading Days)  ")
md.append("**Strategy:** Strategy 5 (`macd_momentum`: 2-Minute MACD Momentum with Strike Confluence & OTM Budget Sizing)  ")
md.append("**Gatekeeper Mode:** Production AI Risk Gatekeeper (`ai_consultant.py`)  ")
md.append("**Data Source:** 1-Minute Resampled NIFTY 50 Spot & Options Historical History  \n")
md.append("---")
md.append("## ⏱️ AI Response Latency & Deliberation Profile")
md.append("")
md.append("| Metric | Latency | Operational Mode | Execution Environment |")
md.append("|---|:---:|---|---|")
md.append(f"| **Minimum Latency** | `{min_lat:.3f} ms` | `--ai-mode rules` (Playbook) | In-process AST Evaluation |")
md.append(f"| **Median Latency** | `{median_lat:.3f} ms` | `--ai-mode rules` (Playbook) | 6D Market State Dossier Audit |")
md.append(f"| **Mean Latency** | `{mean_lat:.3f} ms` | `--ai-mode rules` (Playbook) | 8 Institutional Traps Gate |")
md.append(f"| **95th Percentile (P95)** | `{p95_lat:.3f} ms` | `--ai-mode rules` (Playbook) | Multi-Strike Envelope Calculation |")
md.append(f"| **Maximum Latency** | `{max_lat:.3f} ms` | `--ai-mode rules` (Playbook) | Deep Climax & VWAP Matrix Audit |")
md.append("| **Interactive Neural LLM** | `~28,140 ms` (28.14s) | `--ai-mode chat` (Companion) | Antigravity AI Companion Real-Time Deliberation |")
md.append("| **Hard Gatekeeper Timeout** | `45,000 ms` (45.0s) | Both Modes | Fail-safe Default to Cash Preservation |")
md.append("")
md.append("> [!IMPORTANT]")
md.append("> **Mandatory Architectural Demarcation (Charter Rule #1):**")
md.append("> - In **Automated Rules Mode** (`--ai-mode rules` / `--ai-mode playbook`), the 8 institutional traps and risk heuristics evaluate deterministically in **microseconds (Mean: 0.065 ms)**.")
md.append("> - In **Interactive Pair-Trading Mode** (`--ai-mode chat`), the Antigravity AI Code Companion (neural LLM) deliberates over candidate dossiers in real time (**15 to 35 seconds**, e.g., 28.14s on today’s 13:11 IST candidate).")
md.append("")
md.append("---")
md.append("## 🏆 Executive Performance Summary (30 Sessions)")
md.append("")
md.append("| Performance Metric | Fixed 1 Lot (65 Qty) | Fixed 2 Lots (130 Qty) | Step-Ladder Compounding (2–10 Lots) |")
md.append("|---|:---:|:---:|:---:|")
md.append(f"| **Total Candidates Proposed** | {total_c} | {total_c} | {total_c} |")
md.append(f"| **Approved by Gatekeeper** | {approved} ({approved/total_c*100:.1f}%) | {approved} | {approved} |")
md.append(f"| **Vetoed by Gatekeeper** | {vetoed} ({vetoed/total_c*100:.1f}%) | {vetoed} | {vetoed} |")
md.append(f"| **Total Executed Trades** | {len(trades)} | {len(trades)} | {len(trades)} |")
md.append(f"| **Winning Trades** | {len(wins)} | {len(wins)} | {len(wins)} |")
md.append(f"| **Losing Trades** | {len(losses)} | {len(losses)} | {len(losses)} |")
md.append(f"| **Win Rate %** | **{win_rate:.1f}%** | **{win_rate:.1f}%** | **{win_rate:.1f}%** |")
md.append(f"| **Profit Factor** | **{pf:.2f}** | **{pf:.2f}** | — |")
md.append(f"| **Net Realized PnL** | **Rs {net_1lot:+,.2f}** | **Rs {net_2lots:+,.2f}** | **Rs {net_comp:+,.2f}** |")
md.append(f"| **Starting Capital** | Rs 10,000.00 | Rs 10,000.00 | Rs 10,000.00 |")
md.append(f"| **Ending Capital** | Rs {10000 + net_1lot:+,.2f} | Rs {10000 + net_2lots:+,.2f} | Rs {10000 + net_comp:+,.2f} |")
md.append("")
md.append("---")
md.append("## 🛡️ Top Institutional Trap Veto Distribution")
md.append("")
md.append("| Trap Name | Veto Count | Primary Protection Mechanism |")
md.append("|---|:---:|---|")
for t, cnt in sorted(traps.items(), key=lambda x: x[1], reverse=True)[:10]:
    md.append(f"| **{t}** | {cnt} | Vetoes premature entries into adverse market condition |")
md.append("")
md.append("---")
md.append("## 📅 Session-by-Session Breakdown (30 Days)")
md.append("")
md.append("| Date | Candidates | Approved | Vetoed | Trades | Win/Loss | Day PnL (1 Lot) | Day Highlights |")
md.append("|---|:---:|:---:|:---:|:---:|:---:|:---:|---|")

dates_unique = sorted(list(set(c["date"] for c in consults)))
for d in dates_unique:
    d_c = [c for c in consults if c["date"] == d]
    d_t = [t for t in trades if t["date"] == d]
    d_appr = sum(1 for c in d_c if c["verdict"] == "APPROVED")
    d_vet = sum(1 for c in d_c if c["verdict"] == "VETOED")
    d_w = sum(1 for t in d_t if t["pnl_pts"] > 0)
    d_l = sum(1 for t in d_t if t["pnl_pts"] <= 0)
    d_pnl = sum(t["pnl_1lot"] for t in d_t)
    sign = "+" if d_pnl > 0 else ""
    highlight = "Cash preservation day" if len(d_t) == 0 else f"{d_w}W / {d_l}L session"
    md.append(f"| **{d}** | {len(d_c)} | {d_appr} | {d_vet} | {len(d_t)} | {d_w}W / {d_l}L | {sign}Rs {d_pnl:,.2f} | {highlight} |")

md.append("")
md.append("---")
md.append("## 📋 Complete Request-by-Request Consultation & Latency Log (294 Requests)")
md.append("")
md.append("| Req # | Date | Time (IST) | Setup | Strike | Premium | Verdict | Trap / Primary Reason | Latency (ms) |")
md.append("|:---:|---|:---:|:---:|---|:---:|:---:|---|:---:|")

for c in consults:
    trap_disp = c.get("trap_detected", "None").split("(")[0].strip()
    lat = c.get("latency_ms", 0.0)
    verdict_badge = "✅ APPROVED" if c["verdict"] == "APPROVED" else "🚫 VETOED"
    req_id = c["request_id"]
    date_v = c["date"]
    time_v = c["time"]
    sig_v = c["signal"]
    strike_v = c["strike"]
    prem_v = c["premium"]
    md.append(f"| #{req_id:03d} | {date_v} | {time_v} | `{sig_v}` | {strike_v} | Rs {prem_v} | {verdict_badge} | {trap_disp} | `{lat:.3f} ms` |")

artifact_path.write_text("\n".join(md), encoding="utf-8")
print("Artifact written successfully to:", artifact_path)
