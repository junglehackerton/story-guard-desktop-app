"""Actual repository/Chroma/Qwen integration, separate disposable project data."""
from pathlib import Path
import sys,json,time,tempfile,hashlib
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.services.rag import RagService
out=root/'output/validation/embedding-advanced'
data=json.loads((out/'dataset.json').read_text());work=Path(tempfile.mkdtemp(prefix='lifecycle-',dir=out))
repo=StoryRepository(Database(work/'evaluation.sqlite'));project=repo.create_project('심화 검사 전용')
model=str(root/'.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf')
rag=RagService(work/'chroma',embedding_model=model,repository=repo)
counts=[];original=rag.embeddings.embed_documents
rag.embeddings.embed_documents=lambda texts:(counts.append(len(texts)) or original(texts))
checks=[];docs={}
def record(name,ok,**extra):
 row={'name':name,'passed':bool(ok),**extra};checks.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
def sync():
 counts.clear();start=time.monotonic();rag.sync_project(project.id);return sum(counts),time.monotonic()-start
for chapter in data['chapters']:
 ch=chapter['chapter'];text=chapter['text'];doc=repo.add_document(project.id,work/f'{ch}.txt',f'{ch}화','txt',hashlib.sha256(text.encode()).hexdigest(),text,ch-1);docs[ch]=doc
 repo.replace_chunks(project.id,doc.id,[c.text for c in rag.split_text(text,doc.id,project.id)])
 if ch in (10,30,50):
  previous=sum(1 for p in data['passages'] if p['chapter']<=(0 if ch==10 else 10 if ch==30 else 30))
  total=len(repo.list_chunks(project.id));embedded,secs=sync()
  record(f'growth_{ch}',embedded==total-previous,embedded_chunks=embedded,total_chunks=total,seconds=secs)
embedded,secs=sync();record('unchanged_sync',embedded==0,embedded_chunks=embedded,seconds=secs)
# A second service instance must reuse the persisted collection and marker.
reopened=RagService(work/'chroma',embedding_model=model,repository=StoryRepository(Database(work/'evaluation.sqlite')))
reopen_counts=[];raw=reopened.embeddings.embed_documents
reopened.embeddings.embed_documents=lambda texts:(reopen_counts.append(len(texts)) or raw(texts))
reopened.sync_project(project.id);record('reopen_no_reembedding',sum(reopen_counts)==0)
old=docs[18];old_ids={str(c['id']) for c in repo.list_chunks(project.id) if c['document_id']==old.id}
source=data['chapters'][17]['text'];old_fact='18화. 유나는 스승 앞에서 봉인검과 정식 계약을 맺었다. 그날부터 사용 자격이 생겼다.'
new_fact='18화. 유나는 스승 앞에서 봉인검의 정식 계약을 끝내 거절했다. 그날에도 계약은 성립하지 않았다.'
assert old_fact in source;new=source.replace(old_fact,new_fact)
new_chunks=[c.text for c in rag.split_text(new,old.id,project.id)]
repo.replace_document(old.id,work/'18-revised.txt','txt',hashlib.sha256(new.encode()).hexdigest(),new,new_chunks)
embedded,secs=sync();stored=rag._collection(project.id).get(include=['documents','metadatas'])
record('revision_index',not old_ids.intersection(stored['ids']) and all(old_fact not in t for t in stored['documents']) and any(new_fact in t for t in stored['documents']),embedded_chunks=embedded,expected_chunks=len(new_chunks),seconds=secs)
record('revision_only_changed_document',embedded==len(new_chunks))
hits=rag.retrieve(project.id,'유나는 봉인검의 정식 계약을 맺었는가?',limit=4)
record('revision_retrieval',any(new_fact in h['text'] for h in hits),hits=[{'id':h['chunk_id'],'chapter':h['chapter_index']+1,'text':h['text']} for h in hits])
repo.delete_document(old.id);embedded,secs=sync();stored=rag._collection(project.id).get(include=['metadatas']);hits=rag.retrieve(project.id,'유나 봉인검 계약',limit=8)
record('deletion',all(m['document_id']!=old.id for m in stored['metadatas']) and all(h['document_id']!=old.id for h in hits),embedded_chunks=embedded,seconds=secs)
record('deletion_no_reembedding',embedded==0)
hits=rag.retrieve(project.id,'봉인검 계약',limit=8,start_chapter=0,end_chapter=9)
record('chapter_filter',bool(hits) and all(0<=h['chapter_index']<=9 for h in hits),chapters=[h['chapter_index']+1 for h in hits])
other=repo.create_project('격리 검사용');text='다른 작품에서 유나는 봉인검 계약을 취소했다. 격리표식 별도세계.'
doc=repo.add_document(other.id,work/'other.txt','다른 작품','txt','other',text,0);repo.replace_chunks(other.id,doc.id,[text]);rag.sync_project(other.id)
hits=rag.retrieve(project.id,'격리표식 별도세계 유나 봉인검',limit=8)
record('project_isolation',all(h['project_id']==project.id and '격리표식' not in h['text'] for h in hits))
# A new late episode must become searchable through the ordinary retrieve-triggered sync.
text='51화. 수정 정원의 관리인은 별빛 우편함을 처음 설치했다. 우편함의 개방 암호는 새벽의 종소리다.'
doc=repo.add_document(project.id,work/'51.txt','51화','txt','addition',text,50);repo.replace_chunks(project.id,doc.id,[text]);counts.clear();hits=rag.retrieve(project.id,'별빛 우편함을 여는 암호는?',limit=4)
record('addition',any(text==h['text'] for h in hits) and sum(counts)==1,embedded_chunks=sum(counts))
report={'scope':'Actual RagService + SQLite + Chroma + Qwen, default local GPU setting; timings not comparable with CPU model benchmark','dataset_sha256':hashlib.sha256((out/'dataset.json').read_bytes()).hexdigest(),'work_dir':str(work),'checks':checks,'passed':sum(c['passed'] for c in checks),'total':len(checks)}
(out/'lifecycle.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
