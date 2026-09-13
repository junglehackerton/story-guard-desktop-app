"""Build the standalone remote technical deck using bundled licensed fonts."""
from pathlib import Path
import base64
import html

root = Path(__file__).resolve().parents[1]
source = (root / 'source/technical-slides.html').read_text()
for key, filename in [('sans', 'PretendardVariable.woff2'), ('serif', 'SourceSerif4-Semibold.woff2')]:
    data = base64.b64encode((root / 'fonts' / filename).read_bytes()).decode()
    source = source.replace('{{font-' + key + '}}', 'data:font/woff2;base64,' + data)
licenses = '\n\n'.join(p.read_text() for p in sorted((root / 'fonts').glob('*LICENSE*')))
source = source.replace('{{licenses}}', html.escape(licenses))
assert '{{' not in source, 'Unresolved placeholder'
output = root / 'story-guard-technical.html'
output.write_text(source)
print(f'{output} ({output.stat().st_size / 1024 / 1024:.1f} MiB)')
