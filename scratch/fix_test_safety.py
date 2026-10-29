path = "tests/test_path_a_safety.py"
with open(path, "r", encoding="utf-8") as fp:
    content = fp.read()

updated = content.replace('trade["last_bid"] = 79', 'trade["last_bid"] = 69')
with open(path, "w", encoding="utf-8") as fp:
    fp.write(updated)
print("Updated test_path_a_safety.py")
