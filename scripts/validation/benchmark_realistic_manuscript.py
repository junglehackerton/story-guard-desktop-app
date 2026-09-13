"""Measure local embedding cost on a realistic-length Korean manuscript sample."""
from __future__ import annotations

import json
import os
import resource
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))

from backend.app.services.embedding_models import GemmaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

out = root / "output/validation/realistic-manuscript-20260912"
out.mkdir(parents=True, exist_ok=True)
model_dir = root / ".cache/embedding-bench-models"

cast = [
    ("유나", "도윤", "봉인검", "은하성문"), ("서린", "태오", "흑요 나침반", "북쪽 관문"),
    ("아린", "민재", "기억의 열쇠", "침묵의 도서관"), ("하린", "도겸", "청동 나팔", "붉은 협곡"),
    ("나래", "시우", "별의 인장", "수몰된 항구"), ("리아", "건우", "유리 가면", "달빛 시장"),
    ("채원", "현우", "망각의 지도", "서쪽 폐성"), ("소담", "이안", "푸른 창", "안개 습지"),
    ("다온", "주원", "겨울의 서약", "얼어붙은 성벽"), ("해나", "준서", "금빛 나뭇잎", "오래된 정원"),
]
templates = [
    "{hero}는 {place}의 새벽 종이 세 번 울린 뒤에야 눈을 떴다. 전날 밤 {companion}이 남긴 쪽지는 창틀에 접혀 있었고, 잉크가 번진 마지막 줄에는 {item}의 이름이 적혀 있었다.",
    "시장으로 내려가는 계단에는 밤새 내린 비가 고여 있었다. {hero}는 사람들의 시선을 피하며 {item}을 품 안쪽에 숨겼다. {companion}은 아무렇지 않은 얼굴로 앞장섰지만, 손가락으로 같은 신호를 세 번 반복했다.",
    "성문을 지키는 감시자는 통행증보다 오래된 규칙을 먼저 물었다. {hero}가 대답하지 않자 {companion}은 과거의 계약을 설명했다. 그러나 계약서의 빈 칸 하나가 두 사람의 기억과 맞지 않았다.",
    "낮이 깊어질수록 {place}의 골목은 조용해졌다. 기록관은 사라진 사람들의 이름을 한 줄씩 읽었고, {hero}는 그 목록 끝에서 자신의 이름과 닮은 흔적을 발견했다.",
    "해가 기울 무렵 {item}이 미세하게 떨렸다. 그것은 단순한 금속음이 아니라 누군가 멀리서 문을 두드리는 소리처럼 들렸다. {companion}은 사용 조건을 확인한 뒤에야 손을 내밀었다.",
    "밤의 회랑에서 두 사람은 서로 다른 증언을 맞춰 보았다. 첫 번째 증언은 {place}의 북문을 가리켰고, 두 번째 증언은 같은 시간에 북문이 닫혀 있었다고 말했다.",
    "다음 날 기록을 정리하면서 {hero}는 전날의 장면을 문장마다 다시 적었다. 사실과 추측을 다른 색으로 나누자, 아무도 설명하지 않은 빈 시간이 선명하게 드러났다.",
    "먼 곳에서 경보가 울리자 군중이 한꺼번에 움직였다. {companion}은 {hero}를 뒤로 밀어 숨겼고, {item}을 사용하면 문이 열리지만 정식 증표가 없으면 대가를 치른다는 사실을 낮게 말했다.",
]

def make_episode(index: int) -> str:
    hero, companion, item, place = cast[index - 1]
    paragraphs = []
    for round_no in range(7):
        for template in templates:
            paragraphs.append(template.format(hero=hero, companion=companion, item=item, place=place))
            paragraphs.append(f"{index}화의 기록 {round_no + 1}-{len(paragraphs)}. {hero}는 주변 인물의 말과 자신의 판단을 구분해 수첩에 옮겼다. {place}에서 확인한 단서는 {item}의 행방, 계약의 조건, 그리고 {companion}이 감추는 과거에 관한 것이었다. 확인되지 않은 소문은 물음표를 붙여 남겼고, 직접 본 장면만 다음 행동의 근거로 삼았다.")
    return "\n\n".join(paragraphs)[:6200]

splitter = RecursiveCharacterTextSplitter(chunk_size=480, chunk_overlap=48, separators=["\n\n", "\n", ". ", "。", "!", "?", " ", ""])
texts = [make_episode(i) for i in range(1, 11)]
chunks = [doc.page_content for text in texts for doc in splitter.create_documents([text]) if doc.page_content.strip()]
model = GemmaEmbeddings(model_dir=model_dir)
start = time.monotonic(); model.embed_query("계약 조건과 봉인 도구의 사용 근거"); warmup_seconds = time.monotonic() - start
start = time.monotonic(); vectors = []
for offset in range(0, len(chunks), 16):
    vectors.extend(model.embed_documents(chunks[offset:offset + 16]))
index_seconds = time.monotonic() - start

import numpy as np
matrix = np.asarray(vectors, dtype=np.float32)
matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
queries = ["정식 계약자가 아니면 봉인검을 사용할 수 없는 조건", "기록관이 확인한 사라진 사람의 이름과 빈 시간", "문을 열 때 필요한 증표와 대가"]
query_timings = []
for query in queries:
    start = time.monotonic(); vector = np.asarray(model.embed_query(query), dtype=np.float32); vector /= max(float(np.linalg.norm(vector)), 1e-12)
    top = np.argsort(-(matrix @ vector))[:4]
    query_timings.append({"query": query, "seconds": round(time.monotonic() - start, 3), "top_chunk_indexes": top.tolist()})
result = {"chapters": len(texts), "chars_per_chapter": [len(text) for text in texts], "total_chars": sum(map(len, texts)), "chunks": len(chunks), "model": "EmbeddingGemma-300M FP32 isolated worker", "warmup_seconds": round(warmup_seconds, 2), "index_seconds": round(index_seconds, 2), "mean_query_seconds": round(sum(item["seconds"] for item in query_timings) / len(query_timings), 3), "max_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1), "queries": query_timings, "scope": "실제 GPT 요청·최종 충돌 판정은 포함하지 않는 로컬 임베딩·검색 비용 측정"}
worker = next(iter(GemmaEmbeddings._workers.values()), None)
if worker is not None:
    result["worker_pid"] = worker.pid
    try:
        import psutil
        result["worker_rss_mb"] = round(psutil.Process(worker.pid).memory_info().rss / (1024 * 1024), 1)
    except Exception:
        result["worker_rss_mb"] = None
(out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
(out / "manuscripts.json").write_text(json.dumps({str(i + 1): text for i, text in enumerate(texts)}, ensure_ascii=False))
print(json.dumps(result, ensure_ascii=False, indent=2))
