import re, sys, unicodedata
from pathlib import Path

ROOT = Path('.').resolve()
FILES = [p for p in ROOT.rglob('*.md')
         if '.git' not in p.parts and 'agent-handoffs' not in p.parts]

def slug(text):
    text = text.strip().lower()
    text = re.sub(r'`([^`]*)`', r'\1', text)
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'[^\w\- ]', '', text, flags=re.UNICODE)
    return re.sub(r'\s+', '-', text)

headings = {}
for f in FILES:
    hs = set()
    for line in f.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^(#{1,6})\s+(.*)$', line)
        if m:
            hs.add(slug(m.group(2)))
    headings[f] = hs

link_re = re.compile(r'\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
bad, checked = [], 0
for f in FILES:
    text = f.read_text(encoding='utf-8')
    # strip fenced code
    body = re.sub(r'```.*?```', '', text, flags=re.S)
    for target in link_re.findall(body):
        if target.startswith(('http://', 'https://', 'mailto:')):
            continue
        checked += 1
        path_part, _, anchor = target.partition('#')
        target_path = (f.parent / path_part).resolve() if path_part else f
        if path_part and not target_path.exists():
            bad.append((str(f.relative_to(ROOT)), target, 'missing file'))
            continue
        if anchor and target_path.suffix == '.md':
            if target_path not in headings:
                headings[target_path] = set(
                    slug(m.group(2)) for m in
                    (re.match(r'^(#{1,6})\s+(.*)$', l)
                     for l in target_path.read_text(encoding='utf-8').splitlines()) if m)
            if anchor.lower() not in headings[target_path]:
                bad.append((str(f.relative_to(ROOT)), target, 'missing anchor'))

print(f"files={len(FILES)} relative_links={checked} problems={len(bad)}")
for b in bad:
    print(' -', *b)
sys.exit(1 if bad else 0)
