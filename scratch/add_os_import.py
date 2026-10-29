with open('trading/application/scheduler.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace("import logging\n", "import logging\nimport os\n", 1)

with open('trading/application/scheduler.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Added import os to trading/application/scheduler.py")
