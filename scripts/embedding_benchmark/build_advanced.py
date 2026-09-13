"""Frozen length/distractor stress fixture, deliberately reusing baseline facts."""
from pathlib import Path
import sys, json, re, hashlib, random
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from backend.app.services.rag import RagService
out=root/'output/validation/embedding-advanced';out.mkdir(parents=True,exist_ok=True)
base=json.loads((root/'output/validation/embedding-comparison/dataset.json').read_text())
facts=[p for p in base['passages'] if p['id'].startswith('s')]
rng=random.Random(91703)
people=['유나','도윤','하린','미르','세온','나래','아라','서린','미라','나린','서림','상단주']
places=['북쪽 성문','지하 도서관','국경 검문소','진료소','오래된 우물','왕궁 회랑','강변 창고','항구','성내 우체국','남쪽 성문']
tasks=['젖은 장부의 글씨를 다시 옮겼다','파손된 수레의 바퀴를 고쳤다','어제 받은 물품의 수량을 대조했다','건물 벽에 난 균열을 살폈다','교대 근무자의 이름을 적었다','낯선 발자국을 따라갔다','창고에서 사라진 곡식을 조사했다','돌아오지 않은 동료를 기다렸다']
items=['은빛 열쇠','구리 열쇠','붉은 인장','푸른 통행증','봉인검','유리검','회상경','귀환석','아버지의 편지','붕대']
paragraphs=[];chapters=[];passages=[]
rag=RagService(out/'splitter-only')
for ch in range(1,51):
 paras=[]
 for i in range(14):
  a,b=rng.sample(people,2);place=rng.choice(places);item=rng.choice(items)
  paras.append(f'{a}는 {place}에서 {rng.choice(tasks)}. {b}는 {item}에 관한 소문을 들었다고 했지만 출처는 밝히지 않았다. 두 사람은 그 말을 공식 규칙으로 기록하지 않기로 했다. 장부에는 {ch*17+i}개의 물품이 적혀 있었으나 실제로 확인된 수량은 달랐다. {rng.choice(people)}는 해가 지기 전에 다시 조사하겠다고 약속했다.')
 selected=[p for p in facts if int(re.match(r'(\d+)화',p['text'])[1])==ch]
 for j,p in enumerate(selected):paras.insert(2+j*3,p['text'])
 text='\n\n'.join(paras);chapters.append({'chapter':ch,'text':text})
 for i,c in enumerate(rag.split_text(text,ch,1)):
  passages.append({'id':f'ch{ch}c{i}','text':c.text,'chapter':ch})
queries=[]
byid={p['id']:p['text'] for p in facts}
for q in base['queries']:
 gold=[];groups=[]
 for gid in q['gold']:
  matches=[p['id'] for p in passages if byid[gid] in p['text']]
  assert matches,gid
  gold+=matches;groups.append(matches)
 queries.append({**q,'gold':gold,'gold_groups':groups,'gold_texts':[byid[g] for g in q['gold']]})
data={'scope':'50 synthetic chapters; repeated templates with seeded variations; baseline questions reused as length/distractor stress, not independent accuracy validation','chapters':chapters,'passages':passages,'queries':queries}
p=out/'dataset.json';p.write_text(json.dumps(data,ensure_ascii=False,indent=2));sha=hashlib.sha256(p.read_bytes()).hexdigest();(out/'dataset.sha256').write_text(sha+'\n')
print({'chapters':50,'characters':sum(len(c['text']) for c in chapters),'chunks':len(passages),'questions':len(queries),'sha256':sha})
