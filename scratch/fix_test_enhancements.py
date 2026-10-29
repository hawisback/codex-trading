with open('tests/test_market_enhancements.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''        dossier.vwap_blender_warning = True
        self.assertIn("Trap 1", AIConsultant().evaluate(dossier).trap_detected)'''

replacement = '''        dossier.option_entry_price = 8.0
        dossier.is_expiry_0dte = True
        self.assertIn("Trap 2", AIConsultant().evaluate(dossier).trap_detected)'''

assert target in content
new_content = content.replace(target, replacement, 1)
with open('tests/test_market_enhancements.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print("Updated test_market_enhancements.py")
