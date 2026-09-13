from pathlib import Path
import sys,tempfile,os,json
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.services.rag import RagService
out=root/'output/validation/embedding-advanced';work=Path(tempfile.mkdtemp(prefix='model-switch-',dir=out));os.environ['STORY_GUARD_DATA_DIR']=str(work)
(work/'models').symlink_to(root/'.cache/embedding-bench-models',target_is_directory=True)
repo=StoryRepository(Database(work/'db.sqlite'));p=repo.create_project('모델 전환 검사');text='정식 계약자만 봉인검을 사용할 수 있다.';d=repo.add_document(p.id,work/'a.txt','1화','txt','a',text,0);repo.replace_chunks(p.id,d.id,[text])
checks=[];collections=[]
models=[str(root/'.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf'),'embeddinggemma-300m',str(root/'.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf')]
try:
 for model in models:
  rag=RagService(work/'chroma',model,repo);hits=rag.retrieve(p.id,'봉인검 사용 조건',strategy='hybrid');checks.append(any(h['text']==text for h in hits));collections.append(rag._collection_name(p.id))
 passed=all(checks) and collections[0]==collections[2] and collections[0]!=collections[1]
 result={'status':'passed' if passed else 'failed','checks':checks,
         'separate_indexes':len(collections) >= 2 and collections[0] != collections[1],
         'qwen_index_reused':len(collections) == 3 and collections[0] == collections[2]}
 if not passed: result['error']='모델별 검색 또는 인덱스 격리 조건을 만족하지 못했습니다.'
except Exception as exc:
 result={'status':'failed','stage':'embedding_runtime','checks':checks,'separate_indexes':False,'qwen_index_reused':False,'error':str(exc)}
(out/'model-switch.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
if result['status'] != 'passed': raise SystemExit(1)
