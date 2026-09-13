"""Continue the failed sequence within its original cumulative six-call allowance."""
from scripts.validate_revision_sequence import *

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-remaining-requests", action="store_true", required=True)
    parser.parse_args()

    root=Path(__file__).resolve().parents[1]
    out=root/'output/validation/revision-sequence'
    run=max(out.glob('run-*'),key=lambda p:p.stat().st_mtime)
    report=json.loads((run/'results.json').read_text())
    assert report['requests']==1 and report.get('error')=='연결 검증 시간이 초과되었습니다.'
    repo=StoryRepository(Database(run/'test.sqlite'))
    project=next(p for p in repo.list_projects() if p.title=='충돌')
    history=repo.review_history(project.id)
    assert history and all(h['status']=='deferred' and h['outcome']=='pending' for h in history)
    report['failure_preserved_history']=True
    rag=RagService(run/'chroma',embedding_model=str(root/'.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf'),repository=repo)
    connection=ChatGptConnection(root/'.cache/chatgpt-integration')
    calls=report['requests'];original=connection.complete

    def limited(*a,**kw):
        nonlocal calls
        if calls>=6:raise RuntimeError('최대 6회 누적 요청 제한')
        calls+=1
        return original(*a,**kw)
    connection.complete=limited
    try:
        target=repo.list_documents(project.id)[1]
        old_ids={r['id'] for r in repo.list_chunks(project.id) if r['document_id']==target.id}
        text='다음 날 아침, 유나는 봉인검과 정식 계약을 맺었다. 그날 저녁 계약자인 유나는 봉인검을 사용해 성문을 열었다.'
        repo.replace_document(target.id,run/'2-revised.txt','txt',hashlib.sha256(text.encode()).hexdigest(),text,[text])
        start=time.monotonic()
        result=GptStoryAnalyzer(repo,rag,connection).analyze(project.id,'gpt-6-astra','low')
        graph=repo.graph(project.id)
        history=repo.review_history(project.id)
        stage={'stage':'시간 초과 후 2화 수정본 재분석','seconds':round(time.monotonic()-start,2),'result':result,'issues':[i.model_dump() for i in graph.issues], 'history':[{'status':h['status'],'outcome':h['outcome']} for h in history], 'old_source_removed':not old_ids.intersection(map(int,rag._collection(project.id).get()['ids'])) and not repo.get_chunks(list(old_ids))}
        stage['passed']=not graph.issues and stage['old_source_removed'] and all(h['status']=='deferred' and h['outcome']=='not_redetected' for h in history)
        report['stages'].append(stage)
        print(json.dumps(stage,ensure_ascii=False),flush=True)
        start=time.monotonic();before=calls
        result=GptStoryAnalyzer(repo,rag,connection).analyze(project.id,'gpt-6-astra','low')
        stage={'stage':'동일 수정본 재분석 캐시','seconds':round(time.monotonic()-start,2),'result':result,'passed':calls==before and not repo.graph(project.id).issues}
        report['stages'].append(stage);print(json.dumps(stage,ensure_ascii=False),flush=True)
    except Exception as error:
        report['recovery_error']=str(error)
        raise
    finally:
        report['requests']=calls
        (run/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        connection.transport.close()

if __name__ == "__main__":
    main()
