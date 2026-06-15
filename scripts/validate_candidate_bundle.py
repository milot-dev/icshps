from pathlib import Path
import yaml

bundle_dir = Path('data/hiring_bundles/candidate_intelligence_test_bundle')
errors = []

for p in bundle_dir.rglob('*.yaml'):
    try:
        content = yaml.safe_load(p.read_text(encoding='utf-8'))
    except Exception as e:
        errors.append(f"{p}: {e}")

if errors:
    print('ERROR')
    for e in errors:
        print(e)
    raise SystemExit(1)

print('OK')
