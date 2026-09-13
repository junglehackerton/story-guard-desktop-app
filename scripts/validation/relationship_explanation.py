"""Two-request live subscription check using synthetic text and an isolated database.
This isolates relation extraction/storage, not embedding or large-manuscript accuracy.
"""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer
from backend.app.services.chatgpt import ChatGptConnection
from backend.app.config import app_data_dir

out=Path('output/validation/relationship-explanation')
out.mkdir(parents=True,exist_ok=True)
# Use the same data-directory resolver as the app so validation observes the
# user's persisted device-code connection instead of an obsolete app path.
connection=ChatGptConnection(app_data_dir())
try:
    try:
        models=connection.models()
    except Exception as error:
        failure={'status':'failed','stage':'connection','error':str(error),
                 'scope':'실제 사용자 GPT 연결 검증 전 단계. 합성 관계 분석과 원문 근거 검사는 실행하지 않음.'}
        (out/'live-result.json').write_text(json.dumps(failure,ensure_ascii=False,indent=2))
        print(json.dumps(failure,ensure_ascii=False),flush=True)
        raise SystemExit(1) from error
    model=next((m for m in models if 'luna' in m['id'].lower()),models[0])
    effort='low' if any(e['value']=='low' for e in model['efforts']) else model['default_effort']
    with TemporaryDirectory(prefix='storyguard-relations-') as folder:
        repo=StoryRepository(Database(Path(folder)/'test.sqlite'))
        project=repo.create_project('관계 설명 가상 검증')
        texts=['도윤은 청백회의 감시를 피해 아린을 보호했다. 아린은 도윤을 친구라고 불렀다.',
               '아린은 도윤이 비밀을 넘겼다고 의심했다. 그러나 도윤의 배신은 확인되지 않았다. 도윤은 여전히 아린을 보호했다.']
        for i,text in enumerate(texts):
            doc=repo.add_document(project.id,Path(folder)/f'{i}.txt',f'{i+1}화 가상 원고','txt',f'fixture-{i}',text,i)
            repo.replace_chunks(project.id,doc.id,[text])
        rows=repo.list_chunks(project.id)
        rag=SimpleNamespace(sync_project=lambda _:len(rows),retrieve=lambda *a,**k:[{'chunk_id':r['id'],'text':r['text']} for r in rows])
        print('Running two synthetic passages with',model['id'],effort,flush=True)
        calls=[]
        def recorded_complete(*args,**kwargs):
            response=connection.complete(*args,**kwargs)
            calls.append(response['text'])
            (out/'synthetic-responses.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2))
            return response
        result=GptStoryAnalyzer(repo,rag,SimpleNamespace(complete=recorded_complete)).analyze(project.id,model['id'],effort)
        graph=repo.graph(project.id).model_dump(mode='json')
        all_claims=[c for r in graph['relations'] for c in r['claims']]
        checks={'has_relations':bool(graph['relations']), 'all_have_explanations':bool(all_claims) and all(r['claims'] for r in graph['relations']),
                'no_generic_type':all(r['type'] not in ['관계','관련'] for r in graph['relations']),
                'quotes_exact':all(q['quote'] in texts[q['chapter_index']] for c in all_claims for q in c['quotes']),
                'both_chapters_cited':{q['chapter_index'] for c in all_claims for q in c['quotes']}=={0,1}}
        report={'model':model['id'],'effort':effort,'scope':'synthetic, two chunks, supplied-context retrieval; not embedding accuracy','result':result,'checks':checks,'graph':graph}
        (out/'live-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps({'result':result,'checks':checks},ensure_ascii=False),flush=True)
        if not all(checks.values()):raise SystemExit('Some checks failed; inspect report.')
finally:
    connection.transport.close()
