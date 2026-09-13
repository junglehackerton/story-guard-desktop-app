"""Measure Qwen GGUF embedding runtime without invoking GPT analysis."""
from __future__ import annotations

import json
import os
import resource
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))

from backend.app.services.local_ai import DEFAULT_EMBEDDING_MODEL, LocalLlmEmbeddings
from backend.app.services.rag import RagService

episodes = int(os.getenv("STORYGUARD_QWEN_BENCH_EPISODES", "10"))
chars_per_episode = int(os.getenv("STORYGUARD_QWEN_BENCH_CHARS_PER_EPISODE", "6200"))
model_path = root / ".cache/model-validation" / DEFAULT_EMBEDDING_MODEL
if not model_path.is_file():
    raise SystemExit(f"Qwen model not found: {model_path}")

base = "유나는 새벽 항구에서 봉인된 기록을 펼쳤다. 도윤은 계약 조건을 확인했고 경비대는 종루를 지켰다. "
splitter = RagService.__new__(RagService)
chunks: list[str] = []
for episode in range(episodes):
    text = (base * ((chars_per_episode // len(base)) + 1))[:chars_per_episode]
    chunks.extend(chunk.text for chunk in splitter.split_text(text, episode + 1, 1))

embedding = LocalLlmEmbeddings(model=str(model_path))
started = time.perf_counter()
embedding.embed_query("계약 조건과 봉인검 사용 근거")
warmup_seconds = time.perf_counter() - started
started = time.perf_counter()
vectors: list[list[float]] = []
for offset in range(0, len(chunks), 16):
    vectors.extend(embedding.embed_documents(chunks[offset : offset + 16]))
index_seconds = time.perf_counter() - started
usage = resource.getrusage(resource.RUSAGE_SELF)
rss_bytes = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
result = {
    "episodes": episodes,
    "chars": episodes * chars_per_episode,
    "chunks": len(chunks),
    "vectors": len(vectors),
    "warmup_seconds": round(warmup_seconds, 3),
    "index_seconds": round(index_seconds, 3),
    "chunks_per_second": round(len(chunks) / index_seconds, 3) if index_seconds else None,
    "max_rss_mb": round(rss_bytes / (1024 * 1024), 1),
    "user_cpu_seconds": round(usage.ru_utime, 3),
    "system_cpu_seconds": round(usage.ru_stime, 3),
    "model": DEFAULT_EMBEDDING_MODEL,
    "scope": "실제 llama.cpp GGUF 임베딩 비용; GPT 분석 품질·Chroma 저장·장편 전체 시간 제외",
}
output = root / "output/validation/realistic-manuscript-20260912/qwen-runtime.json"
output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
