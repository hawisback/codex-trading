import sys
import re
import json
from collections import defaultdict
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def main():
    log_file = "logs/trader.log"
    print("=" * 80)
    print("FORENSIC AUDIT OF TRADER.LOG - WEDNESDAY, OCTOBER 14, 2026")
    print("=" * 80)

    # Patterns to capture
    # 1. Blocks / filters
    # 2. Consultations & Verdicts
    # 3. Orders & Execution

    timeline = []
    block_counts = defaultdict(int)
    rejection_reasons = []

    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not ("2026-10-14 " in line):
                continue
            
            # Timestamp
            ts_match = re.search(r"2026-10-14 (\d{2}:\d{2}:\d{2})", line)
            if not ts_match:
                continue
            time_str = ts_match.group(1)

            # Categorize events
            if "Candidate Signal:" in line or "Signal Candidate" in line:
                timeline.append((time_str, "CANDIDATE", line.strip()))
            elif "BLOCKED:" in line:
                # Extract block reason
                m = re.search(r"(BLOCKED:.*?)(?:\.|$)", line)
                reason = m.group(1) if m else line.strip()
                block_counts[reason] += 1
                # Record specific key moments
                if any(k in line for k in ["ORDER FLOW", "CLIMAX", "CHASE", "PULLBACK BLOCKED"]):
                    # Sample every few minutes or key shifts
                    timeline.append((time_str, "BLOCK", reason))
            elif "Consultation" in line or "Dossier" in line:
                if any(k in line for k in ["Triggering", "Starting", "Verdict", "VETO", "APPROVED"]):
                    timeline.append((time_str, "AI_CONSULT", line.strip()))
            elif "HTTP 422" in line or "REJECTED" in line or "Insufficient funds" in line:
                timeline.append((time_str, "REJECTION", line.strip()))
            elif "Submitting" in line or "FILLED" in line or "Ratcheting" in line or "Placing Resting Stop" in line or "Cancelled" in line:
                timeline.append((time_str, "EXECUTION", line.strip()))

    print(f"\nTotal Key Events Extracted: {len(timeline)}")

    # Summary of Block Reasons
    print("\n" + "=" * 80)
    print("BLOCK REASONS FREQUENCY ACROSS THE ENTIRE SESSION:")
    print("=" * 80)
    for reason, count in sorted(block_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  [{count:4d}x] {reason}")

    # Detailed Timeline of Candidate Opportunities and Trade Actions
    print("\n" + "=" * 80)
    print("CHRONOLOGICAL TIMELINE OF CANDIDATES, SIGNALS, VETOES & EXECUTIONS:")
    print("=" * 80)
    
    last_printed_block = ""
    last_block_time = ""
    for ts, ev_type, content in timeline:
        if ev_type == "BLOCK":
            # Avoid printing every single second of the same block
            if content == last_printed_block:
                last_block_time = ts
                continue
            else:
                if last_printed_block:
                    print(f"  ... [repeated until {last_block_time}]")
                last_printed_block = content
                last_block_time = ts
                print(f"[{ts}] {ev_type:<10} | {content}")
        else:
            if last_printed_block:
                print(f"  ... [blocks ended at {last_block_time}]")
                last_printed_block = ""
            print(f"[{ts}] {ev_type:<10} | {content}")

if __name__ == "__main__":
    main()
