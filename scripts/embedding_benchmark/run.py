"""Local-only, frozen corpus benchmark. Run each model in a separate process."""
from pathlib import Path
import argparse,json,hashlib,time,resource,platform,statistics,os
os.environ['STORY_GUARD_GPU_LAYERS']='0'
os.environ['TOKENIZERS_PARALLELISM']='false'
os.environ['HF_HUB_OFFLINE']='1'
import numpy as np
parser=argparse.ArgumentParser();parser.add_argument('model',choices=['qwen','e5','bge','gemma']);parser.add_argument('--dataset');parser.add_argument('--output');args=parser.parse_args()
root=Path(__file__).resolve().parents[2];out=root/'output/validation/embedding-comparison'
out=Path(args.output) if args.output else out
out.mkdir(parents=True,exist_ok=True)
p=Path(args.dataset) if args.dataset else out/'dataset.json';data=json.loads(p.read_text());digest=hashlib.sha256(p.read_bytes()).hexdigest()
assert args.dataset or digest=='669a46c4affc011e132993a4f7c6e6e9fbb18382e73ab16743dcafca3581955a'
start=time.perf_counter();lengths=[]
if args.model=='qwen':
 from backend.app.services.local_ai import LocalLlmEmbeddings,QUERY_INSTRUCTION
 modelpath=root/'.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf'
 model=LocalLlmEmbeddings(str(modelpath))
 from llama_cpp import Llama,LLAMA_POOLING_TYPE_LAST
 llm=Llama(model_path=str(modelpath),embedding=True,pooling_type=LLAMA_POOLING_TYPE_LAST,n_ctx=2048,n_batch=2048,n_ubatch=2048,n_threads=4,n_gpu_layers=0,offload_kqv=False,verbose=False)
 model._llm_cache[model.identity()]=llm
 def encode(text,query=False):
  value=f'Instruct: {QUERY_INSTRUCTION}\nQuery: {text}' if query else text
  lengths.append(len(llm.tokenize(value.encode())))
  return np.asarray(model.embed_query(text) if query else model.embed_documents([text])[0])
 runtime='llama.cpp / GGUF Q8 / CPU 4 threads';size=modelpath.stat().st_size
elif args.model=='gemma':
 import torch,transformers,sentence_transformers
 from sentence_transformers import SentenceTransformer
 torch.set_num_threads(4);torch.set_num_interop_threads(1)
 modelpath=root/'.cache/embedding-bench-models/embeddinggemma-300m'
 model=SentenceTransformer(str(modelpath),device='cpu',local_files_only=True,trust_remote_code=False,model_kwargs={'torch_dtype':torch.float32})
 model.eval()
 def encode(text,query=False):
  prompt=model.prompts['query' if query else 'document']
  length=len(model.tokenizer(prompt+text,truncation=False)['input_ids']);lengths.append(length)
  assert length<=min(2048,model.max_seq_length), 'Input exceeds model limit; do not silently truncate'
  value=model.encode_query(text,show_progress_bar=False,convert_to_numpy=True) if query else model.encode_document(text,show_progress_bar=False,convert_to_numpy=True)
  assert np.isfinite(value).all() and abs(np.linalg.norm(value)-1)<1e-4
  return value
 runtime=f'torch {torch.__version__} / transformers {transformers.__version__} / sentence-transformers {sentence_transformers.__version__} / FP32 CPU 4 threads'
 size=sum(f.stat().st_size for f in modelpath.rglob('*') if f.is_file() and '.cache' not in f.relative_to(modelpath).parts)

else:
 import torch,transformers
 from transformers import AutoModel,AutoTokenizer
 torch.set_num_threads(4);torch.set_num_interop_threads(1)
 modelpath=root/'.cache/embedding-bench-models'/('multilingual-e5-small' if args.model=='e5' else 'bge-m3')
 tokenizer=AutoTokenizer.from_pretrained(modelpath,local_files_only=True)
 model=AutoModel.from_pretrained(modelpath,local_files_only=True,trust_remote_code=False).eval()
 def encode(text,query=False):
  if args.model=='e5':text=('query: ' if query else 'passage: ')+text
  inputs=tokenizer(text,return_tensors='pt',truncation=False)
  length=inputs['input_ids'].shape[1];lengths.append(length)
  assert length<=(512 if args.model=='e5' else 8192), 'Input exceeds model limit; do not silently truncate'
  with torch.inference_mode():
   hidden=model(**inputs).last_hidden_state
   if args.model=='e5':
    mask=inputs['attention_mask'].unsqueeze(-1);v=(hidden*mask).sum(1)/mask.sum(1)
   else:v=hidden[:,0]
   return torch.nn.functional.normalize(v,p=2,dim=1)[0].numpy()
 runtime=f'torch {torch.__version__} / transformers {transformers.__version__} / FP32 CPU 4 threads'
 size=sum(f.stat().st_size for f in modelpath.rglob('*') if f.is_file() and '.cache' not in f.relative_to(modelpath).parts)
load=time.perf_counter()-start
encode(data['passages'][0]['text'])
start=time.perf_counter();encoded=[]
for i,p in enumerate(data['passages']):
 encoded.append(encode(p['text']))
 if (i+1)%25==0:print(f'Indexed {i+1}/{len(data["passages"])}',flush=True)
vectors=np.stack(encoded);index_seconds=time.perf_counter()-start
np.savez_compressed(out/f'{args.model}-vectors.npz',vectors=vectors)
results=[];times=[]
for q in data['queries']:
 start=time.perf_counter();v=encode(q['query'],True);scores=vectors@v;rank=np.argsort(-scores,kind='stable');times.append(time.perf_counter()-start)
 ranked=[data['passages'][i]['id'] for i in rank];gold=set(q['gold']);top=set(ranked[:4]);groups=q.get('gold_groups',[[g] for g in q['gold']]);ranks=[min(ranked.index(g)+1 for g in group) for group in groups]
 results.append({**q,'top4':ranked[:4],'top8':ranked[:8],'gold_ranks':sorted(ranks),'recall_at4':sum(r<=4 for r in ranks)/len(ranks),'all_at4':all(r<=4 for r in ranks),'rr':1/min(ranks)})
start=time.perf_counter();encode('서린은 금고의 암호가 바뀌었음을 확인했다.');update_ms=(time.perf_counter()-start)*1000
categories={c:{'count':sum(q['category']==c for q in results),'all_at4':statistics.mean(q['all_at4'] for q in results if q['category']==c)} for c in sorted({q['category'] for q in results})}
report={'model':args.model,'dataset_sha256':digest,'runtime':runtime,'hardware':platform.machine(),'load_seconds':load,'index_seconds':index_seconds,'query_p50_ms':statistics.median(times)*1000,'query_p95_ms':float(np.percentile(times,95))*1000,'single_update_embed_ms':update_ms,'peak_process_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024**2,'model_files_mib':size/1024**2,'dimensions':vectors.shape[1],'max_input_tokens':max(lengths),'passages':len(vectors),'questions':len(results),'recall_at4':statistics.mean(q['recall_at4'] for q in results),'all_at4':statistics.mean(q['all_at4'] for q in results),'mrr':statistics.mean(q['rr'] for q in results),'categories':categories,'results':results}
(out/f'{args.model}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False,indent=2))
