from pathlib import Path
import sys,json,time,numpy as np
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from backend.app.services.embedding_models import GemmaEmbeddings
out=root/'output/validation/embedding-advanced'
data=json.loads((out/'dataset.json').read_text());model=GemmaEmbeddings(root/'.cache/embedding-bench-models')
start=time.monotonic();model.embed_query('가속 준비');load=time.monotonic()-start
start=time.monotonic();vectors=np.asarray(model.embed_documents([p['text'] for p in data['passages']]));seconds=time.monotonic()-start
passed=0
for q in data['queries']:
 v=np.asarray(model.embed_query(q['query']));rank=np.argsort(-(vectors@v));top={data['passages'][i]['id'] for i in rank[:4]}
 passed+=all(top.intersection(g) for g in q['gold_groups'])
r={'model':'EmbeddingGemma FP32 isolated worker auto acceleration batch8','warmup_seconds':load,'index_seconds':seconds,'top4':passed,'questions':len(data['queries']),'chunks':len(vectors)}
(out/'gemma-app.json').write_text(json.dumps(r,indent=2));print(r)
