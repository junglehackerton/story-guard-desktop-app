"""Fresh synthetic cases frozen before scoring; actual Qwen/Chroma, no GPT."""
from pathlib import Path
import sys,json,tempfile,hashlib,time
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.services.rag import RagService
out=root/'output/validation/retrieval-strategies';out.mkdir(parents=True,exist_ok=True)
scenes=[
['달빛 나침반은 밤에만 방향을 가리킨다.','리온이 태양 수정을 달빛 나침반에 끼우면 낮에도 방향을 확인할 수 있다.','대낮에 리온은 태양 수정을 끼운 달빛 나침반으로 북쪽을 찾았다.','낮에 나침반을 사용할 수 있게 된 조건과 원래 제한은?'],
['흑요 방패는 한 번 깨지면 다시 복구할 수 없다.','세라는 흑요 방패의 잔해를 버리고 같은 모양의 새 강철 방패를 만들었다.','세라는 다음 전투에 멀쩡한 강철 방패를 들고 왔다.','세라의 방패가 멀쩡한 이유와 부서진 방패의 원래 성질은?'],
['서쪽 탑 출입에는 파란 배지가 필요하다.','화재 대피 때에는 배지 없이도 서쪽 탑 비상문으로 나갈 수 있다.','배지가 없는 이안은 화재가 나자 서쪽 탑 비상문으로 탈출했다.','배지가 없는 이안의 통행을 검토할 규정과 예외는?'],
['눈꽃 약초는 열을 가하면 해독 효능을 잃는다.','약사 로아는 열을 가한 눈꽃 약초를 향료로만 쓰고 별도의 돌꽃 뿌리로 해독제를 만들었다.','로아는 끓인 눈꽃 약초와 돌꽃 뿌리를 함께 넣어 환자의 독을 치료했다.','끓인 약초로 독을 치료한 장면의 기존 제약과 다른 해독 재료는?'],
['해무 다리는 성인 둘이 함께 올라가면 무너진다.','수리공 에단은 해무 다리 아래 철제 기둥을 세워 성인 열 명의 무게를 견디도록 보강했다.','에단과 동료 셋이 수리를 마친 해무 다리를 동시에 건넜다.','여럿이 다리를 건넌 사건을 판단할 예전 한계와 보강 근거는?'],
['청동 종은 소리를 내면 경비병을 부른다.','잠입자 노엘은 청동 종의 추를 천으로 감싸 소리가 나지 않게 했다.','노엘이 청동 종을 움직였지만 경비병은 오지 않았다.','종을 움직였는데 경비병이 오지 않은 이유와 원래 작동 조건은?']]
f=out/'fresh-cases.json';f.write_text(json.dumps(scenes,ensure_ascii=False,indent=2));digest=hashlib.sha256(f.read_bytes()).hexdigest()
work=Path(tempfile.mkdtemp(prefix='fresh-',dir=out));repo=StoryRepository(Database(work/'db.sqlite'));project=repo.create_project('미사용 사례 검색 검사');rag=RagService(work/'chroma',str(root/'.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf'),repo)
for i,scene in enumerate(scenes):
 for j,text in enumerate(scene[:3]):
  text='길가에는 오래된 여행 기록이 남아 있었다. 두 사람은 전날의 날씨를 이야기하며 젖은 짐을 정리했다.\n\n'+text+'\n\n일행은 다음 마을의 숙소와 저녁 식사를 의논했다.'
  d=repo.add_document(project.id,work/f'{i}-{j}.txt',f'{i}-{j}','txt',str(i*3+j),text,i*3+j);repo.replace_chunks(project.id,d.id,[text])
# Related words in unrelated facts, without inserting gold answers.
for i,text in enumerate(['달빛 그림은 낮과 밤의 모습을 그린 작품이다.','파란 배지는 상점에서 장식품으로도 팔린다.','돌꽃은 정원 식물 그림의 제목이다.','청동 거울을 움직여도 종소리는 들리지 않는다.']):
 d=repo.add_document(project.id,work/f'noise{i}.txt',f'noise{i}','txt',f'n{i}',text,30+i);repo.replace_chunks(project.id,d.id,[text])
rag.sync_project(project.id);cases=[]
for i,scene in enumerate(scenes):
 for kind,query in [('question',scene[3]),('manuscript',scene[2])]:
  scores={};rankings={};timings={}
  for strategy in ['dense','hybrid']:
   start=time.monotonic();hits=rag.retrieve(project.id,query,limit=4,strategy=strategy);timings[strategy]=time.monotonic()-start
   scores[strategy]=all(any(g in h['text'] for h in hits) for g in scene[:2]);rankings[strategy]=[h['text'] for h in hits]
  cases.append({'scene':i,'kind':kind,'query':query,'gold':scene[:2],'success':scores,'hits':rankings,'seconds':timings})
report={'sha256':digest,'scope':'12 fresh synthetic queries, six new scenarios; half manuscript-style. Not human-authored independent evaluation. Qwen actual Chroma default local GPU setting.','cases':cases,'dense':sum(c['success']['dense'] for c in cases),'hybrid':sum(c['success']['hybrid'] for c in cases),'gained':sum(c['success']['hybrid'] and not c['success']['dense'] for c in cases),'lost':sum(c['success']['dense'] and not c['success']['hybrid'] for c in cases)}
(out/'fresh-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False))
