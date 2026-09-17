"""Quality gates for the natural serial fixture."""
from pathlib import Path
import hashlib
import sys

ROOT = Path(__file__).resolve().parents[2]
FILES = sorted((ROOT / 'output/validation/natural-novel-20260914/episodes').glob('episode-*.txt'))
paragraphs = [p.strip() for f in FILES for p in f.read_text(encoding='utf-8').split('\n\n') if p.strip()]
lengths = [len(f.read_text(encoding='utf-8')) for f in FILES]
fingerprints = [hashlib.sha1(p.encode()).hexdigest() for p in paragraphs]
duplicate_rate = 1 - len(set(fingerprints)) / max(1, len(fingerprints))
adjacent_duplicates = sum(a == b for a, b in zip(paragraphs, paragraphs[1:]))
print(f'episodes={len(FILES)} lengths={lengths}')
print(f'paragraphs={len(paragraphs)} duplicate_rate={duplicate_rate:.3%} adjacent_duplicates={adjacent_duplicates}')
if len(FILES) != 10 or min(lengths, default=0) < 8000 or duplicate_rate >= 0.05 or adjacent_duplicates:
    print('QUALITY_GATE=FAIL')
    sys.exit(1)
print('QUALITY_GATE=PASS')
