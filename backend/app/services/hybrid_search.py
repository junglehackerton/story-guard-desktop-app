"""Local paragraph BM25 and bounded fusion with semantic retrieval."""
from collections import Counter
import math
import re


def _terms(text: str) -> list[str]:
    words = re.findall(r'[가-힣a-zA-Z0-9]+', text.lower())
    return [word[i:i + size] for word in words for size in (2, 3)
            for i in range(len(word) - size + 1)]


def lexical_rank(rows: list[dict], query: str) -> list[dict]:
    terms = set(_terms(query))
    if not terms or not rows:
        return []
    paragraphs = [(i, Counter(_terms(text))) for i, row in enumerate(rows)
                  for text in row['text'].split('\n\n') if text.strip()]
    if not paragraphs:
        return []
    frequency = Counter(term for _, counts in paragraphs for term in counts)
    average = sum(sum(counts.values()) for _, counts in paragraphs) / len(paragraphs)
    if not average:
        return []
    scores = [0.0] * len(rows)
    for i, counts in paragraphs:
        length = sum(counts.values())
        score = sum(math.log(1 + (len(paragraphs) - frequency[t] + .5) / (frequency[t] + .5))
                    * counts[t] * 2.2 / (counts[t] + 1.2 * (.25 + .75 * length / average))
                    for t in terms if counts[t])
        scores[i] = max(scores[i], score)
    return [rows[i] for i in sorted(range(len(rows)), key=lambda i: -scores[i]) if scores[i] > 0]


def merge_rankings(dense: list[dict], lexical: list[dict], limit: int) -> list[dict]:
    if limit <= 0:
        return []
    split = (limit + 1) // 2
    ordered = dense[:split] + lexical[:limit - split] + dense + lexical
    result, seen = [], set()
    for row in ordered:
        # Chroma returns metadata values with the native SQLite type while
        # the repository/lexical path can return the same ID as a string.
        # Normalize before de-duplicating; otherwise a dense hit such as 22
        # and a lexical hit such as "22" occupy two result slots and can push
        # the actual rare-rule evidence out of a small top-k window.
        key = str(row['chunk_id'])
        if key not in seen:
            seen.add(key)
            result.append(row)
            if len(result) == limit:
                break
    return result
