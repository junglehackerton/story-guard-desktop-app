"""Bounded real GPT comparison: two local embedding models, at most eight requests."""
from pathlib import Path
import sys,tempfile,os,json,time,hashlib
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.services.rag import RagService
from backend.app.services.chatgpt import ChatGptConnection
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer
out=root/'output/validation/model-e2e';out.mkdir(parents=True,exist_ok=True)
run=Path(tempfile.mkdtemp(prefix='run-',dir=out));connection=ChatGptConnection(root/'.cache/chatgpt-integration');original=connection.complete
report={'model':'gpt-6-astra','effort':'low','request_limit':8,'requests':0,'scope':'Actual app services and GPT connection in separate DB, two-chunk synthetic manuscripts. Does not benchmark retrieval selectivity or UI upload latency.','cases':[]}
def persist():
 (run/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));(out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
def limited(*a,**kw):
 if report['requests']>=8:raise RuntimeError('최대 8회 요청 도달')
 report['requests']+=1;persist();return original(*a,**kw)
connection.complete=limited
rule='봉인검은 예외 없이 정식 계약자만 사용할 수 있다. 유나는 계약 제안을 거절했다.'
action='다음 날, 유나는 여전히 계약을 맺지 않은 상태로 봉인검을 사용해 성문을 열었다.'
revision='다음 날 아침, 유나는 스승 앞에서 봉인검과 정식 계약을 맺었다. 저녁에는 계약자인 유나가 봉인검을 사용해 성문을 열었다.'
try:
 for name,model in [('qwen',str(root/'.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf')),('gemma','embeddinggemma-300m')]:
  work=run/name;work.mkdir();os.environ['STORY_GUARD_DATA_DIR']=str(work);(work/'models').symlink_to(root/'.cache/embedding-bench-models',target_is_directory=True)
  repo=StoryRepository(Database(work/'db.sqlite'));p=repo.create_project('실제 GPT 통합 검증 '+name);rag=RagService(work/'chroma',model,repo);docs=[]
  for i,text in enumerate([rule,action]):
   d=repo.add_document(p.id,work/f'{i}.txt',f'{i+1}화','txt',hashlib.sha256(text.encode()).hexdigest(),text,i);repo.replace_chunks(p.id,d.id,[text]);docs.append(d)
  analyzer=GptStoryAnalyzer(repo,rag,connection)
  entry={'embedding':name,'stages':[]};report['cases'].append(entry)
  for stage in ['conflict','cached_decision','revised_exception']:
   if stage=='cached_decision':
    for issue in repo.graph(p.id).issues:repo.update_issue_status(issue.id,'deferred')
   if stage=='revised_exception':
    old_ids={c['id'] for c in repo.list_chunks(p.id) if c['document_id']==docs[1].id}
    repo.replace_document(docs[1].id,work/'revised.txt','txt',hashlib.sha256(revision.encode()).hexdigest(),revision,[revision])
   before=report['requests'];start=time.monotonic()
   try:
    result=analyzer.analyze(p.id,'gpt-6-astra','low');issues=repo.graph(p.id).issues
    passed=bool(issues) if stage=='conflict' else bool(issues) and all(i.status=='deferred' for i in issues) and report['requests']==before if stage=='cached_decision' else not issues and not repo.get_chunks(list(old_ids))
    record={'stage':stage,'passed':passed,'seconds':time.monotonic()-start,'requests':report['requests']-before,'issues':[i.model_dump() for i in issues],'result':result}
    if stage=='revised_exception':
     record['old_index_removed']=not old_ids.intersection(map(int,rag._collection(p.id).get()['ids']));record['passed']=record['passed'] and record['old_index_removed']
     record['history']=[{'status':h['status'],'outcome':h['outcome']} for h in repo.review_history(p.id)]
   except Exception as error:
    record={'stage':stage,'passed':False,'error':str(error),'seconds':time.monotonic()-start,'requests':report['requests']-before}
   entry['stages'].append(record);persist();print(name,stage,record['passed'],record['requests'],flush=True)
   if 'error' in record:break
finally:connection.transport.close();persist()
