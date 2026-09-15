"""Quality gate for the deterministic long-manuscript fixture."""
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "output/validation/long-manuscript-20260913/episodes"
MIN_CHARS_PER_EPISODE = 10000


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


files = sorted(ROOT.glob("episode-*.txt"))
paragraphs: list[str] = []
sentences: list[str] = []
lengths: list[int] = []
short_episodes: list[tuple[str, int]] = []
structural_repeats: list[tuple[str, float]] = []
for path in files:
    text = path.read_text(encoding="utf-8")
    lengths.append(len(text))
    if len(text) < MIN_CHARS_PER_EPISODE:
        short_episodes.append((path.name, len(text)))
    chunks = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    for paragraph in chunks[1:]:
        paragraphs.append(paragraph)
        sentences.extend(
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?。！？])\s+", paragraph)
            if sentence.strip()
        )
    for left, right in zip(chunks[1:], chunks[2:]):
        ratio = SequenceMatcher(None, normalize(left), normalize(right)).ratio()
        if ratio >= 0.78:
            structural_repeats.append((path.name, round(ratio, 3)))

paragraph_dups = sum(count - 1 for count in Counter(map(normalize, paragraphs)).values() if count > 1)
sentence_dups = sum(count - 1 for count in Counter(map(normalize, sentences)).values() if count > 1)
adjacent_dups = sum(a == b for a, b in zip(paragraphs, paragraphs[1:]))
passed = (
    len(files) == 10
    and min(lengths, default=0) >= 10000
    and paragraph_dups == 0
    and sentence_dups == 0
    and adjacent_dups == 0
    and not structural_repeats
)
print(
    {
        "files": len(files),
        "chars": lengths,
        "paragraphs": len(paragraphs),
        "sentences": len(sentences),
        "duplicate_paragraphs": paragraph_dups,
        "duplicate_sentences": sentence_dups,
        "adjacent_duplicates": adjacent_dups,
        "short_episodes": short_episodes,
        "adjacent_structural_repeats": structural_repeats[:10],
        "QUALITY_GATE": "PASS" if passed else "FAIL",
    }
)
sys.exit(0 if passed else 1)
