"""Build an offline, single-file presentation; Python standard library only."""
from pathlib import Path
import base64
import html

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT.parent / 'design' / 'references'

def uri(path, mime):
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode()

template = (ROOT / 'source' / 'slides.html').read_text()
for path in REFERENCES.glob('*.png'):
    template = template.replace('{{' + path.stem + '}}', uri(path, 'image/png'))
for path in (ROOT.parent / 'design' / 'desktop-teal').glob('*.png'):
    template = template.replace('{{desktop-' + path.stem + '}}', uri(path, 'image/png'))
for key, filename in [('sans', 'PretendardVariable.woff2'), ('serif', 'SourceSerif4-Semibold.woff2')]:
    template = template.replace('{{font-' + key + '}}', uri(ROOT / 'fonts' / filename, 'font/woff2'))
licenses = '\n\n'.join(p.read_text() for p in sorted((ROOT / 'fonts').glob('*LICENSE*')))
template = template.replace('{{licenses}}', html.escape(licenses))
assert '{{' not in template, 'Unresolved template placeholder'
output = ROOT / 'story-guard.html'
output.write_text(template)
print(f'{output} ({output.stat().st_size / 1024 / 1024:.1f} MiB)')
