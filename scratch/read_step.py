import json

target_steps = [2767, 3943, 4070, 4074]
with open(r'C:\Users\hawis\.gemini\antigravity\brain\12b9612f-02ad-41a8-a4e7-6c03a05bf7fb\.system_generated\logs\transcript.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line: continue
        try:
            d = json.loads(line)
            if d.get('step_index') in target_steps and d.get('source') == 'USER_EXPLICIT':
                print(f"=== STEP {d.get('step_index')} ===")
                print(d.get('content'))
        except Exception:
            pass
