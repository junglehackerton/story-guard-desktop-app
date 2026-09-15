"""Validate model-authored manuscript files; never generate prose.

The old fixture generator produced noun-swapped sentence skeletons. This gate
only accepts already-authored text and rejects repeated syntactic frames.
"""
from collections import Counter
from pathlib import Path
import re, sys

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
MIN_EPISODES = 10
MIN_CHARS = 10_000

def frame(sentence: str) -> str:
    s = re.sub(r"\s+", " ", sentence.strip())
    # Collapse names, numbers and quoted payload while preserving syntax.
    s = re.sub(r"[가-힣]{2,4}(?=은|는|이|가|을|를|의|에게|에서)", "<주어>", s)
    s = re.sub(r"\d+", "<수>", s)
    s = re.sub(r"“[^”]*”|\"[^\"]*\"", "<대사>", s)
    return s

files = sorted(ROOT.glob("episode-*.txt"))
counts = Counter()
short = []
for path in files:
    text = path.read_text(encoding="utf-8")
    if len(text) < MIN_CHARS:
        short.append((path.name, len(text)))
    for sentence in re.split(r"(?<=[.!?。！？])\s+", text):
        if len(sentence.strip()) >= 20:
            counts[frame(sentence)] += 1
repeated = [(k, v) for k, v in counts.items() if v >= 4]
passed = len(files) >= MIN_EPISODES and not short and not repeated
print({"episodes": len(files), "short": short, "repeated_frames": len(repeated), "examples": repeated[:8], "QUALITY_GATE": "PASS" if passed else "FAIL"})
raise SystemExit(0 if passed else 1)
