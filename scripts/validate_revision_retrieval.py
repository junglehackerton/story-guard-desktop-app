"""Local embedding evaluation of growing manuscripts; never sends GPT requests."""
from pathlib import Path
import sys,json, time, tempfile, hashlib
root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.services.rag import RagService

out = root/'output/validation/revision-retrieval'
out.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp(prefix='run-', dir=out))
repo = StoryRepository(Database(work/'evaluation.sqlite'))
project = repo.create_project('누적·수정·삭제 검색 검증')
rag = RagService(work/'chroma', embedding_model=str(root/'.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf'), repository=repo)
facts = {
 1:'봉인검은 정식 계약자만 사용할 수 있다. 유나는 계약을 거절했다.',
 8:'유나는 스승 앞에서 봉인검과 정식 계약을 맺었다. 이때부터 유나는 계약자다.',
 15:'붉은 인장이 없는 편지는 국경 밖으로 운반할 수 없다.',
 22:'지하 도서관의 문은 은빛 열쇠로만 열린다. 구리 열쇠는 사용할 수 없다.',
 29:'유나는 봉인검으로 성문을 열었다. 전령은 붉은 인장이 없는 편지를 국경 밖으로 운반했다.'}
queries=[('유나는 봉인검의 정식 계약을 언제 맺었는가?',8),('붉은 인장 없이 편지를 국경 밖으로 보낼 수 있는가?',15),('지하 도서관 문을 구리 열쇠로 열 수 있는가?',22),('유나가 봉인검으로 성문을 연 사건',29)]
results=[]; documents={}; counts=[]
validation_failures=[]
original=rag.embeddings.embed_documents

def measured(texts):
 counts.append(len(texts));return original(texts)
rag.embeddings.embed_documents=measured
for chapter in range(1,101):
 text=facts.get(chapter,'')+'\n'+'\n'.join(f'{chapter}화 기록 {i}. 여행자는 마을에서 숙박했다. 상인은 시장에서 곡물을 팔았다. 항구의 배들은 다음 날 출항을 기다렸다.' for i in range(12))
 doc=repo.add_document(project.id,work/f'{chapter}.txt',f'{chapter}화','txt',hashlib.sha256(text.encode()).hexdigest(),text,chapter-1)
 repo.replace_chunks(project.id,doc.id,[c.text for c in rag.split_text(text,doc.id,project.id)])
 documents[chapter]=doc
 if chapter not in (10,30,60,100):continue
 try:
  counts.clear();start=time.monotonic();rag.sync_project(project.id);elapsed=time.monotonic()-start
 except Exception as error:
  failure={
   'status':'failed',
   'stage':'embedding_runtime',
   'chapters':chapter,
   'error':str(error),
   'model':str(rag.embedding_model),
   'scope':'누적 원고 검색 검증이 임베딩 런타임 초기화 전에 중단됨. 검색 품질 통과로 해석하지 않음.',
  }
  (out/'results.json').write_text(json.dumps(failure,ensure_ascii=False,indent=2))
  print(json.dumps(failure,ensure_ascii=False),flush=True)
  raise
 count=sum(counts);checks=[]
 for query,expected in queries:
  if expected>chapter:continue
  # The index was synchronized once at this checkpoint. Avoid reopening and
  # revalidating Chroma for every query; production GPT review uses the same
  # bounded lifecycle and reads the canonical source snapshot once.
  start=time.monotonic();hits=rag.retrieve(project.id,query,limit=4,strategy='hybrid',ensure_index=False)
  found=[h['chapter_index']+1 for h in hits]
  hit=expected in found
  checks.append({'query':query,'expected_chapter':expected,'found':found,'hit':hit,'seconds':round(time.monotonic()-start,3)})
  if not hit:
   validation_failures.append({'checkpoint':chapter,'query':query,'expected_chapter':expected,'found':found})
 results.append({'chapters':chapter,'chunks':len(repo.list_chunks(project.id)),'embedded_chunks':count,'sync_seconds':round(elapsed,3),'queries':checks})
 print(json.dumps(results[-1],ensure_ascii=False),flush=True)
doc=documents[8];old_ids={r['id'] for r in repo.list_chunks(project.id) if r['document_id']==doc.id}
text='ユナではなくユナという人物。 유나는 봉인검의 정식 계약을 끝내 거절했다. 계약은 성립하지 않았다.'
counts.clear();repo.replace_document(doc.id,work/'revision.txt','txt','revised',text,[text]);start=time.monotonic();hits=rag.retrieve(project.id,'유나는 봉인검의 계약을 맺었는가?',limit=4)
revision={'seconds':round(time.monotonic()-start,3),'embedded_chunks':sum(counts),'old_ids_absent':not old_ids.intersection(map(int,rag._collection(project.id).get()['ids'])),'new_text_retrieved':any(h['text']==text for h in hits)}
repo.delete_document(doc.id);counts.clear();hits=rag.retrieve(project.id,'유나 계약',limit=4)
deletion={'deleted_document_absent':all(h['document_id']!=doc.id for h in hits),'index_absent':all(m['document_id']!=doc.id for m in rag._collection(project.id).get()['metadatas']),'embedded_chunks':sum(counts)}
report={'scope':'합성 한국어 원고의 실제 Qwen3 로컬 임베딩 검색 평가. GPT 판단 정확도는 별도 평가 필요.','growth':results,'revision':revision,'deletion':deletion,'validation_failures':validation_failures,'status':'failed' if validation_failures else 'passed'}
(out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'revision':revision,'deletion':deletion,'validation_failures':validation_failures,'status':report['status']},ensure_ascii=False),flush=True)
if validation_failures:
 raise SystemExit(2)
