import glob, re, os
from datetime import datetime

pattern_req = re.compile(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+05:30).*?\[AI CONSULTATION REQUIRED\] request=([a-f0-9]+)')
pattern_verdict = re.compile(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+05:30).*?AI Consultation (APPROVED|VETOED|TIMEOUT):? (.*)')

logs = sorted(glob.glob('logs/trader-2026-10-*.log'))
results = []

for log_path in logs:
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        curr_req = None
        for line in f:
            m_req = pattern_req.search(line)
            if m_req:
                curr_req = {
                    'ts': datetime.fromisoformat(m_req.group(1)),
                    'id': m_req.group(2),
                    'file': os.path.basename(log_path)
                }
            m_verd = pattern_verdict.search(line)
            if m_verd and curr_req:
                v_ts = datetime.fromisoformat(m_verd.group(1))
                delta = (v_ts - curr_req['ts']).total_seconds()
                results.append({
                    'req_id': curr_req['id'],
                    'log': curr_req['file'],
                    'req_ts': curr_req['ts'].isoformat(),
                    'verd_ts': v_ts.isoformat(),
                    'action': m_verd.group(2),
                    'latency_sec': round(delta, 2),
                    'reason': m_verd.group(3)[:100]
                })
                curr_req = None

print(f"Total live AI chat consultations in logs: {len(results)}")
for r in results:
    print(f"{r['log']} | Req: {r['req_ts'][11:19]} -> Verd: {r['verd_ts'][11:19]} | Latency: {r['latency_sec']}s | {r['action']} | {r['reason'][:60]}")
