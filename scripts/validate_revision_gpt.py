"""Opt-in synthetic GPT evaluation. Requires --allow-six-requests and --model."""
from pathlib import Path
import sys,argparse, hashlib, json, tempfile, time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.services.rag import RagService
from backend.app.services.chatgpt import ChatGptConnection
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--allow-six-requests', action='store_true', required=True)
    parser.add_argument('--model',required=True)
    parser.add_argument('--case', choices=['충돌', '계약 체결로 해소', '무관한 내용 추가'])
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    out=root/'output/validation/revision-gpt';out.mkdir(parents=True,exist_ok=True)
    run=Path(tempfile.mkdtemp(prefix='run-',dir=out))
    repo=StoryRepository(Database(run/'test.sqlite'))
    rag=RagService(run/'chroma',embedding_model=str(root/'.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf'),repository=repo)
    connection=ChatGptConnection(root/'.cache/chatgpt-integration')
    calls=0;complete=connection.complete
    def limited(*a,**k):
        nonlocal calls
        if calls>=6:raise RuntimeError('승인된 최대 6회 요청 도달')
        calls+=1
        return complete(*a,**k)
    connection.complete=limited
    results=[]
    rule='봉인검은 예외 없이 정식 계약자만 사용할 수 있다. 유나는 계약을 거절했다.'
    action='다음 날, 유나는 여전히 계약하지 않은 상태로 봉인검을 사용해 성문을 열었다.'
    cases=[('충돌',action,True),('계약 체결로 해소','다음 날 아침, 유나는 봉인검과 정식 계약을 맺었다. 그날 저녁 계약자인 유나는 봉인검을 사용해 성문을 열었다.',False),('무관한 내용 추가',action+' 시장에서는 상인들이 사과를 팔았고 항구에는 배가 도착했다.',True)]
    if args.case:
        cases = [case for case in cases if case[0] == args.case]
    try:
        for title,second,expected in cases:
            project=repo.create_project(title)
            for chapter,text in enumerate([rule,second]):
                doc=repo.add_document(project.id,run/f'{chapter}.txt',f'{chapter+1}화','txt',hashlib.sha256(text.encode()).hexdigest(),text,chapter)
                repo.replace_chunks(project.id,doc.id,[text])
            start=time.monotonic()
            try:
                result=GptStoryAnalyzer(repo,rag,connection).analyze(project.id,args.model,'low')
                graph=repo.graph(project.id)
                results.append({'case':title,'status':'completed','expected_conflict':expected,
                    'passed':bool(graph.issues)==expected,'seconds':round(time.monotonic()-start,2),
                    'result':result,'issues':[i.model_dump() for i in graph.issues]})
            except Exception as error:
                # Keep a durable, sanitized record even when a provider or
                # transport failure aborts the case. This makes the failed
                # window actionable for a later retry instead of losing the
                # only evidence when the process exits non-zero.
                results.append({'case':title,'status':'failed','expected_conflict':expected,
                    'passed':False,'seconds':round(time.monotonic()-start,2),
                    'error':str(error)[:1000],'requests':calls})
                (out/'results.json').write_text(json.dumps({'model':args.model,'effort':'low',
                    'requests':calls,'cases':results},ensure_ascii=False,indent=2))
                print(json.dumps(results[-1],ensure_ascii=False),flush=True)
                break
            (out/'results.json').write_text(json.dumps({'model':args.model,'effort':'low','requests':calls,'cases':results},ensure_ascii=False,indent=2))
            print(json.dumps(results[-1],ensure_ascii=False),flush=True)
    finally: connection.transport.close()

if __name__=='__main__': main()
