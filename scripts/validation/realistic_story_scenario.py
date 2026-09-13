"""Run a deterministic end-to-end Story Guard scenario over an intentionally flawed story.
This validates parser, local analysis projection, relationship graph, issue evidence, and source offsets.
It does not claim local model semantic quality; the fixture extractor represents a model response so
pipeline behaviour can be checked independently from model availability.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.pipeline.analyzer import StoryAnalyzer
from backend.app.services.parser import split_chunks

class ScenarioLlm:
    model='scenario-fixture'
    def enabled(self): return True
    def extract_story_facts(self,text,context='',known_entity_names=None):
        entities=[
            {'type':'character','name':'유나','summary':'봉인검을 발견한 인물','aliases':[]},
            {'type':'character','name':'도윤','summary':'유나를 감시하지만 보호하는 인물','aliases':[]},
            {'type':'organization','name':'회백원','summary':'서고와 규칙을 관리하는 조직','aliases':[]},
            {'type':'item','name':'봉인검','summary':'정식 계약자만 사용할 수 있는 검','aliases':[]},
            {'type':'foreshadowing','name':'붉은 편지','summary':'왕궁의 배신자를 밝힐 단서','aliases':[]},
            {'type':'rule','name':'정식 계약자만 봉인검 사용 가능','summary':'봉인검 사용 조건','aliases':[]},
        ]
        relations=[]
        if '도윤은 유나를 감시하라는 명령' in text:
            relations += [{'source':'도윤','target':'유나','type':'감시함','confidence':0.84},{'source':'도윤','target':'유나','type':'도움','confidence':0.9}]
        if '유나는 도윤을 믿었고' in text:
            relations += [{'source':'유나','target':'도윤','type':'신뢰함','confidence':0.88}]
        if '봉인검' in text:
            relations += [{'source':'유나','target':'봉인검','type':'발견함','confidence':0.86}]
        if '붉은 편지' in text:
            relations += [{'source':'붉은 편지','target':'왕궁','type':'단서가 됨','confidence':0.8}]
        return {'entities':entities,'relations':relations,'issues':[]}
    def detect_continuity_issues(self,text,context='',known_entity_names=None):
        return [{'severity':'high','category':'contradiction','title':'봉인검 사용 조건 충돌','description':'1화와 3화에서 정식 계약자만 사용할 수 있다는 규칙과 무계약 사용이 함께 나타납니다.','evidence_chunk_ids':[]}]

class AllChunks:
    def __init__(self,repo): self.repo=repo
    def sync_project(self,project_id): return len(self.repo.list_chunks(project_id))
    def retrieve(self,project_id,query,limit=4,**kwargs):
        return [{'chunk_id':row['id'],'text':row['text']} for row in self.repo.list_chunks(project_id)[:limit]]

with TemporaryDirectory(prefix='storyguard-realistic-') as tmp:
    root=Path(tmp); repo=StoryRepository(Database(root/'story.sqlite')); project=repo.create_project('회백원과 붉은 편지 · 실사용 검증')
    fixture=ROOT/'output/validation/realistic-story-scenario/chapters'
    for idx,path in enumerate(sorted(fixture.glob('*.txt'))):
        text=path.read_text(); doc=repo.add_document(project.id,path,f'{idx+1}화 · {path.stem}','txt',f'fixture-{idx}',text,idx); repo.replace_chunks(project.id,doc.id,split_chunks(text))
    repo.add_story_setting(project.id,'봉인검 사용 조건','정식 계약자만 봉인검을 사용할 수 있다.','confirmed')
    result=StoryAnalyzer(repo,rag=AllChunks(repo),llm=ScenarioLlm()).analyze_project(project.id)
    graph=repo.graph(project.id).model_dump(mode='json'); rows=repo.list_chunks(project.id)
    text_by_id={r['id']:r['text'] for r in rows}
    issue_quotes=[text_by_id[i] for i in graph['issues'][0]['evidence_chunk_ids'] if i in text_by_id] if graph['issues'] else []
    names={e['name'] for e in graph['entities']}; rel_types={r.get('type',r.get('relation_type','')) for r in graph['relations']}
    checks={
      'four_documents':len(repo.list_documents(project.id))==4,
      'entities_include_characters_item_foreshadowing':{'유나','도윤','봉인검','붉은 편지'}<=names,
      'relationship_extracted':{'감시함','도움','신뢰함'}<=rel_types,
      'continuity_issue_detected':any('봉인검' in i['title'] for i in graph['issues']),
      'issue_has_source_evidence':bool(graph['issues']) and len(graph['issues'][0]['evidence_chunk_ids'])>=2,
      'evidence_points_to_real_text':all(text_by_id[i] for i in graph['issues'][0]['evidence_chunk_ids']) if graph['issues'] else False,
      'foreshadowing_candidate_present':any(e['type']=='foreshadowing' and e['name']=='붉은 편지' for e in graph['entities']),
      'confirmed_setting_saved':any(s.title=='봉인검 사용 조건' and s.certainty=='confirmed' for s in repo.list_story_settings(project.id)),
      'all_relation_chunks_exist':all(cid in text_by_id for r in graph['relations'] for cid in r['evidence_chunk_ids']),
    }
    report={'project':project.title,'fixture':str(fixture.relative_to(ROOT)),'result':result.__dict__ if hasattr(result,'__dict__') else str(result),'checks':checks,'graph_counts':{'entities':len(graph['entities']),'relations':len(graph['relations']),'issues':len(graph['issues']),'chunks':len(rows)},'issue_quotes':issue_quotes,'graph':graph}
    out=ROOT/'output/validation/realistic-story-scenario'; (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'checks':checks,'graph_counts':report['graph_counts']},ensure_ascii=False,indent=2))
    if not all(checks.values()): raise SystemExit('scenario checks failed')
