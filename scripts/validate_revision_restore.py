"""Final two calls in the cumulative six-call sequence; isolated synthetic DB only."""
from scripts.validate_revision_sequence import *

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-remaining-requests", action="store_true", required=True)
    parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    out=root/'output/validation/revision-sequence'
    run=max(out.glob('run-*'),key=lambda p:p.stat().st_mtime)
    report=json.loads((run/'results.json').read_text())
    assert report['requests']==4 and len(report['stages'])==2
    repo=StoryRepository(Database(run/'test.sqlite'))
    project=next(p for p in repo.list_projects() if p.title=='충돌')
    docs=repo.list_documents(project.id)
    assert len(docs)==3
    repo.delete_document(docs[2].id)
    text='다음 날, 유나는 여전히 계약하지 않은 상태로 봉인검을 사용해 성문을 열었다.'
    repo.replace_document(docs[1].id,run/'restored.txt','txt',hashlib.sha256(text.encode()).hexdigest(),text,[text])
    rag=RagService(run/'chroma',embedding_model=str(root/'.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf'),repository=repo)
    connection=ChatGptConnection(root/'.cache/chatgpt-integration')
    calls=report['requests'];original=connection.complete

    def limited(*a,**kw):
        nonlocal calls
        if calls>=6:raise RuntimeError('최대 6회 누적 요청 제한')
        calls+=1;return original(*a,**kw)
    connection.complete=limited
    try:
        start=time.monotonic();result=GptStoryAnalyzer(repo,rag,connection).analyze(project.id,'gpt-6-astra','low')
        issues=repo.graph(project.id).issues
        stage={'stage':'무관한 3화 제거·2화 원래 충돌 복원','seconds':round(time.monotonic()-start,2),'result':result,'issues':[i.model_dump() for i in issues], 'passed':bool(issues) and all(i.status=='deferred' for i in issues)}
        report['stages'].append(stage);print(json.dumps(stage,ensure_ascii=False),flush=True)
    except Exception as error:
        report['restore_error']=str(error);raise
    finally:
        report['requests']=calls
        (run/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        connection.transport.close()

if __name__ == "__main__":
    main()
