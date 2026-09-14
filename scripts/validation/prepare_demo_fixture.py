"""Precompute a portable demo embedding bundle from the natural serial fixture.

This deliberately uses the same RagService splitter and EmbeddingGemma adapter
as the desktop app. It does not call GPT; GPT findings remain an explicit
runtime step (or can be attached later as a reviewed JSON result).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "output/validation/natural-novel-20260914/episodes"
OUT = ROOT / "output/validation/demo-fixture-20260914"
MODEL = ROOT / ".cache/embedding-bench-models/embeddinggemma-300m"

sys.path.insert(0, str(ROOT))
from backend.app.services.embedding_models import _LocalGemmaEmbeddings, gemma_ready  # noqa: E402
from backend.app.services.local_ai import LocalLlmEmbeddings  # noqa: E402
from backend.app.services.rag import RagService  # noqa: E402


def main() -> None:
    files = sorted(SOURCE.glob("episode-*.txt"))
    if len(files) != 10:
        raise SystemExit(f"expected 10 source episodes, found {len(files)}")
    qwen_model = ROOT / ".cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf"
    if not MODEL.is_dir() and not qwen_model.is_file():
        raise SystemExit("no local embedding model cache found")

    splitter = RagService.__new__(RagService)
    rows: list[dict[str, object]] = []
    for chapter_index, path in enumerate(files):
        text = path.read_text(encoding="utf-8")
        chunks = splitter.split_text(text, chapter_index + 1, 1)
        for chunk_index, chunk in enumerate(chunks):
            rows.append({
                "id": f"ep{chapter_index + 1:02d}-chunk{chunk_index:04d}",
                "chapter": chapter_index + 1,
                "chunk": chunk_index,
                "text": chunk.text,
            })

    started = time.perf_counter()
    # Prefer Gemma when its isolated runtime is installed. In a clean checkout
    # the already validated Qwen GGUF is a practical fallback for preparation.
    use_gemma = MODEL.is_dir() and gemma_ready(MODEL.parent)
    embedder = _LocalGemmaEmbeddings(MODEL.parent) if use_gemma else LocalLlmEmbeddings(model=str(qwen_model))
    vectors = embedder.embed_documents([str(row["text"]) for row in rows])
    elapsed = time.perf_counter() - started
    if len(vectors) != len(rows):
        raise SystemExit(f"embedding count mismatch: rows={len(rows)} vectors={len(vectors)}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "chunks.jsonl").write_text(
        "".join(json.dumps({**row, "embedding": vector}, ensure_ascii=False) + "\n"
                for row, vector in zip(rows, vectors)),
        encoding="utf-8",
    )
    metadata = {
        "fixture": "natural-serial-v2",
        "source": str(SOURCE.relative_to(ROOT)),
        "embedding_model": "EmbeddingGemma 300M" if use_gemma else "Qwen3-Embedding-0.6B-Q8",
        "embedding_dimensions": len(vectors[0]) if vectors else 0,
        "episodes": len(files),
        "chunks": len(rows),
        "embedding_seconds": round(elapsed, 3),
        "chunks_per_second": round(len(rows) / elapsed, 3) if elapsed else None,
        "gpt_analysis": "not included; run through the app with the user's connected model",
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
