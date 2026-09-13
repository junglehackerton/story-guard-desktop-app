"""Reproducible, no-GPT-cost long-context retrieval evaluation."""
from pathlib import Path
import json
import sys
import time

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.services.rag import RagService

out = root / 'output/validation/long-retrieval'
out.mkdir(parents=True, exist_ok=True)
repo = StoryRepository(Database(out / 'evaluation.sqlite'))
project = repo.create_project('30회차 합성 검색 평가')
rag = RagService(out / 'chroma', embedding_model=str(root / '.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf'), repository=repo)
facts = {
  1: '봉인검은 정식 계약자만 사용할 수 있으며 예외가 없다. 유나는 아직 계약자가 아니다.',
  8: '유나는 스승과 봉인검의 정식 계약을 맺었다. 그날부터 유나는 봉인검의 계약자다.',
  15: '왕국의 전령은 붉은 인장을 가진 편지만 국경 밖으로 운반할 수 있다.',
  22: '지하 도서관의 문은 은빛 열쇠로만 열리며, 구리 열쇠로는 열 수 없다.',
  29: '유나는 봉인검을 사용해 성문을 열었다. 전령은 붉은 인장이 없는 편지를 국경 밖으로 옮겼다.',
}
queries = [
 {'query': '유나가 봉인검을 쓰기 전에 정식 계약자가 되었는가?', 'chapters': [8]},
 {'query': '봉인검을 사용할 수 있는 계약 조건과 예외 규칙', 'chapters': [1]},
 {'query': '전령이 편지를 국경 밖으로 옮기려면 어떤 인장이 필요한가?', 'chapters': [15]},
 {'query': '지하 도서관 문을 구리 열쇠로 열 수 있는가?', 'chapters': [22]},
 {'query': '유나가 봉인검을 사용한 사건', 'chapters': [29]},
]
chars = 0
for chapter in range(1, 31):
    filler = '\n'.join(f'{chapter}일째 마을 기록 {i}. 시장 상인은 곡물 자루를 정리했다. 골목에서는 아이들이 나무 공을 굴렸고, 여관 주인은 저녁 식탁을 차렸다. 여행자는 비가 그친 뒤 길을 떠나기로 했다.' for i in range(9))
    text = facts.get(chapter, '') + '\n' + filler
    chars += len(text)
    doc = repo.add_document(project.id, out / f'{chapter}.txt', f'{chapter}화', 'txt', str(chapter), text, chapter-1)
    repo.replace_chunks(project.id, doc.id, [c.text for c in rag.split_text(text, doc.id, project.id)])
start = time.monotonic()
try:
    rag.sync_project(project.id)
except Exception as error:
    failure = {
        'status': 'failed',
        'stage': 'index',
        'error': str(error),
        'chapters': 30,
        'model': str(root / '.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf'),
        'scope': '장편 검색 평가를 시작했으나 임베딩 런타임 초기화 단계에서 중단됨. GPT 판단 정확도는 측정하지 않음.',
    }
    (out/'results.json').write_text(json.dumps(failure, ensure_ascii=False, indent=2))
    print(json.dumps(failure, ensure_ascii=False, indent=2))
    raise SystemExit(1) from error
index_seconds = time.monotonic()-start
results=[]
for case in queries:
    start=time.monotonic();hits=rag.retrieve(project.id,case['query'],limit=4)
    found=sorted({h['chapter_index']+1 for h in hits})
    results.append({**case,'found_chapters':found,'hit':set(case['chapters']).issubset(found),'seconds':round(time.monotonic()-start,3)})
report={'characters':chars,'chapters':30,'chunks':len(repo.list_chunks(project.id)),'index_seconds':round(index_seconds,2),'hit_at_4':sum(r['hit'] for r in results)/len(results),'queries':results,'scope':'검색 평가만. GPT 최종 판단 및 실제 장편 소설 정확도는 측정하지 않음.'}
(out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
