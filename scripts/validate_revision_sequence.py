"""Same-project lifecycle check; reuses a previous verified baseline, at most six new GPT calls."""
from pathlib import Path
import sys
import argparse
import hashlib
import json
import sqlite3
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.services.rag import RagService
from backend.app.services.chatgpt import ChatGptConnection
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--allow-six-requests', action='store_true', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = max((root/'output/validation/revision-gpt').glob('run-*/test.sqlite'), key=lambda p:p.stat().st_mtime)
    out = root/'output/validation/revision-sequence'
    out.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=out))
    with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as src, sqlite3.connect(run/'test.sqlite') as dest:
        src.backup(dest)
    repo = StoryRepository(Database(run/'test.sqlite'))
    project = next(p for p in repo.list_projects() if p.title == '충돌')
    documents = repo.list_documents(project.id)
    baseline = repo.graph(project.id)
    assert len(baseline.issues) == 1
    repo.update_issue_status(baseline.issues[0].id, 'deferred')
    rag = RagService(run/'chroma', embedding_model=str(root/'.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf'), repository=repo)
    connection = ChatGptConnection(root/'.cache/chatgpt-integration')
    calls = 0
    original = connection.complete
    def limited(*a, **kw):
        nonlocal calls
        if calls >= 6:
            raise RuntimeError('최대 6회 요청 제한')
        calls += 1
        return original(*a, **kw)
    connection.complete = limited
    report = {'baseline_source':str(source.relative_to(root)), 'model':'gpt-6-astra', 'effort':'low', 'baseline':'이전 실제 GPT 충돌 결과를 복제하여 시작', 'stages':[]}
    def persist():
        report['requests'] = calls
        (run/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        (out/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    def analyze(label):
        start = time.monotonic()
        result = GptStoryAnalyzer(repo,rag,connection).analyze(project.id, 'gpt-6-astra', 'low')
        graph = repo.graph(project.id)
        return {'stage':label,'seconds':round(time.monotonic()-start,2),'result':result,
                'issues':[i.model_dump() for i in graph.issues],
                'history':[{'id':h['id'],'status':h['status'],'outcome':h['outcome']} for h in repo.review_history(project.id)]}
    try:
        text = '시장에서 상인들이 사과를 팔았다. 항구에 배가 도착했다.'
        doc = repo.add_document(project.id,run/'3.txt','무관한 후속 회차','txt',hashlib.sha256(text.encode()).hexdigest(),text,2)
        repo.replace_chunks(project.id,doc.id,[text])
        stage = analyze('무관한 3화 추가 후 작가 판단 유지')
        stage['passed'] = bool(stage['issues']) and all(i['status']=='deferred' for i in stage['issues']) and any(h['outcome']=='redetected' for h in stage['history'])
        report['stages'].append(stage); persist(); print(json.dumps(stage,ensure_ascii=False),flush=True)
        target = documents[1]
        old_ids = {r['id'] for r in repo.list_chunks(project.id) if r['document_id']==target.id}
        text = '다음 날 아침, 유나는 봉인검과 정식 계약을 맺었다. 그날 저녁 계약자인 유나는 봉인검을 사용해 성문을 열었다.'
        revised = repo.replace_document(target.id,run/'2-revised.txt','txt',hashlib.sha256(text.encode()).hexdigest(),text,[text])
        assert revised.id==target.id and revised.chapter_index==target.chapter_index
        stage = analyze('2화 계약 체결 수정 후 미재검출')
        stored = set(map(int,rag._collection(project.id).get()['ids']))
        stage['old_source_removed'] = not old_ids.intersection(stored) and not repo.get_chunks(list(old_ids))
        stage['passed'] = not stage['issues'] and stage['old_source_removed'] and any(h['outcome']=='not_redetected' for h in stage['history'])
        report['stages'].append(stage);persist();print(json.dumps(stage,ensure_ascii=False),flush=True)
        report['passed'] = all(s['passed'] for s in report['stages'])
    except Exception as error:
        report['error'] = str(error);report['passed']=False
        raise
    finally:
        persist();connection.transport.close()

if __name__=='__main__':main()
