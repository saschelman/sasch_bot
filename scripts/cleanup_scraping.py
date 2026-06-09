from pathlib import Path
import re
import shutil

p = Path('scraping')
if not p.exists():
    print('no scraping dir')
    raise SystemExit

groups = {}
for d in p.iterdir():
    if not d.is_dir():
        continue
    m = re.match(r"^(.+?)_(\d{8}_\d{6})$", d.name)
    if m:
        sym = m.group(1)
        ts = m.group(2)
        groups.setdefault(sym, []).append((ts, d))
    else:
        groups.setdefault(d.name, []).append((None, d))

for sym, items in groups.items():
    if len(items) <= 1:
        continue
    # keep item with max timestamp (None considered smallest)
    items_with_ts = [it for it in items if it[0] is not None]
    if not items_with_ts:
        continue
    items_with_ts.sort(key=lambda x: x[0], reverse=True)
    keep = items_with_ts[0][1]
    to_remove = [it[1] for it in items if it[1] != keep]
    for rm in to_remove:
        print('Removing', rm)
        shutil.rmtree(rm)
print('Cleanup complete')
