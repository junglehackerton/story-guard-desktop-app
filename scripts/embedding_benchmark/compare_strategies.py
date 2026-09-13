"""Exploratory retrieval ablation; no model inference, no source mutation."""
from pathlib import Path
from collections import Counter
import json,math,re,html,hashlib
root=Path(__file__).resolve().parents[2];base=root/'output/validation/embedding-advanced';out=root/'output/validation/retrieval-strategies';out.mkdir(parents=True,exist_ok=True)
data=json.loads((base/'dataset.json').read_text());passages=data['passages'];byid={p['id']:p for p in passages}
def tokens(text):
 words=re.findall(r'[가-힣a-zA-Z0-9]+',text.lower())
 return [w[i:i+n] for w in words for n in (2,3) for i in range(len(w)-n+1)]
# Score short paragraphs, then aggregate by source chunk with max score.
paragraphs=[(p['id'],t) for p in passages for t in p['text'].split('\n\n') if t.strip()]
tfs=[Counter(tokens(t)) for _,t in paragraphs];df=Counter(t for tf in tfs for t in tf);avg=sum(map(lambda tf:sum(tf.values()),tfs))/len(tfs)
def lexical(query):
 qt=set(tokens(query));scores={p['id']:0. for p in passages}
 for (pid,_),tf in zip(paragraphs,tfs):
  length=sum(tf.values());score=0.
  for t in qt:
   f=tf[t]
   if f:score+=math.log(1+(len(tfs)-df[t]+.5)/(df[t]+.5))*f*2.2/(f+1.2*(.25+.75*length/avg))
  scores[pid]=max(scores[pid],score)
 return [pid for pid in sorted(scores,key=lambda pid:-scores[pid]) if scores[pid]>0]
def fuse(dense,lex):
 scores={}
 for ranking in (dense,lex[:8]):
  for rank,pid in enumerate(ranking):scores[pid]=scores.get(pid,0)+1/(60+rank+1)
 return sorted(scores,key=lambda pid:-scores[pid])
def neighbor(dense):
 result=[]
 for pid in dense[:2]:
  if pid not in result:result.append(pid)
 for pid in dense[:2]:
  i=next(i for i,p in enumerate(passages) if p['id']==pid)
  for j in (i-1,i+1):
   if 0<=j<len(passages) and passages[j]['chapter']==byid[pid]['chapter'] and passages[j]['id'] not in result:result.append(passages[j]['id'])
 return list(dict.fromkeys(result+dense))
allresults=[]
for name in ['qwen','e5','bge','gemma']:
 model=json.loads((base/f'{name}.json').read_text());cases=[]
 for q in model['results']:
  lex=lexical(q['query']);dense=q['top8'];strategies={'dense4':dense[:4],'paragraph_bm25_4':lex[:4],'rrf4':fuse(dense,lex)[:4],'dense2_lex2':list(dict.fromkeys(dense[:2]+lex[:2]+dense+lex))[:4],'neighbor4':neighbor(dense)[:4]}
  scores={k:all(any(pid in group for pid in ids) for group in q['gold_groups']) for k,ids in strategies.items()}
  cases.append({'query':q['query'],'category':q['category'],'gold_texts':q['gold_texts'],'strategies':strategies,'success':scores})
 summary={k:{'passed':sum(q['success'][k] for q in cases),'gained':sum(q['success'][k] and not q['success']['dense4'] for q in cases),'lost':sum(not q['success'][k] and q['success']['dense4'] for q in cases)} for k in cases[0]['success']}
 allresults.append({'model':name,'summary':summary,'cases':cases})
 print(name,summary,flush=True)
report={'scope':'Exploratory on already inspected synthetic cases; fixed 4-chunk budget; no GPT and no new inference; not independent validation','dataset_sha256':hashlib.sha256((base/'dataset.json').read_bytes()).hexdigest(),'method':'Korean within-word 2/3-character grams; BM25 k1=1.2,b=.75 over paragraphs, max score per chunk; equal RRF k=60 over each top8 list; neighbors stay in chapter. Existing dense top8 cached from actual models.','results':allresults}
(out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
