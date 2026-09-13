"""Real GGUF integration check. Run index and query in separate processes.

python -m scripts.validate_local_rag --model PATH --data-dir TEMP_PATH --stage index
python -m scripts.validate_local_rag --model PATH --data-dir TEMP_PATH --stage query
"""
import argparse
import json
import sys
import time
from pathlib import Path

# Allow direct execution from the repository checkout as documented below.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.services.parser import read_document
from backend.app.services.rag import RagService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--stage', choices=['index', 'query'], required=True)
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    database = Database(args.data_dir / 'story.sqlite')
    database.initialize()
    repo = StoryRepository(database)
    rag = RagService(args.data_dir / 'chroma', embedding_model=str(args.model.resolve()), repository=repo)
    started = time.perf_counter()
    if args.stage == 'index':
        if repo.list_projects():
            raise RuntimeError('검증용 새 데이터 폴더를 지정하세요.')
        for title, exception in [('충돌 후보', False), ('예외 근거 있음', True)]:
            project = repo.create_project(title)
            texts = [
                '1화: 세계관 규칙. 계약자만 봉인검을 사용할 수 있다.',
                '2화: 유나는 제안을 듣고 계약을 거절했다.',
                '7화: 유나는 봉인검을 들어 올려 마물을 베었다.',
                '3화: 유나는 서랍에서 발신인이 없는 편지를 발견했다.',
                '4화: 밤새 비가 내려 시장의 지붕이 젖었다.',
            ]
            if exception:
                texts.append('6화: 유나는 스승과 정식으로 계약을 맺었다. 그날부터 봉인검의 계약자가 되었다.')
            for i, text in enumerate(texts):
                path = args.data_dir / f'{project.id}-{i}.txt'
                path.write_text(text, encoding='utf-8')
                content, fmt, digest = read_document(path)
                doc = repo.add_document(project.id, path, path.stem, fmt, digest, content, chapter_index=int(text[0]))
                chunks = rag.split_text(content, doc.id, project.id)
                repo.replace_chunks(project.id, doc.id, [c.text for c in chunks])
            assert rag.sync_project(project.id) == len(texts)
        result = {'stage': 'index', 'projects': 2, 'chunks': 11}
    else:
        projects = repo.list_projects()
        assert len(projects) == 2
        results = []
        for project in projects:
            for query, expected in [('검을 사용하는 자격과 규칙은?', '계약자만'), ('유나가 계약을 거절한 장면은?', '거절'), ('유나가 봉인검을 사용한 장면은?', '마물을')]:
                hits = rag.retrieve(project.id, query, limit=3)
                assert any(expected in row['text'] for row in hits), (query, hits)
                assert all(repo.get_chunks([row['chunk_id']])[0]['text'] == row['text'] for row in hits)
                results.append({'project': project.title, 'query': query, 'hits': hits})
            hits = rag.retrieve(project.id, '유나가 나중에 계약을 맺어 검을 쓸 수 있게 되었는가?', limit=3)
            has_exception = any('정식으로 계약' in row['text'] for row in hits)
            assert has_exception == (project.title == '예외 근거 있음')
            results.append({'project': project.title, 'exception_retrieved': has_exception, 'hits': hits})
            if has_exception:
                doc = next(doc for doc in repo.list_documents(project.id) if '정식으로 계약' in doc.content)
                repo.delete_document(doc.id)
                hits = rag.retrieve(project.id, '유나가 나중에 계약을 맺었는가?', limit=10)
                assert not any('정식으로 계약' in row['text'] for row in hits)
        result = {'stage': 'query', 'restart_persistence': True, 'deleted_evidence_absent': True, 'results': results}
    result['seconds'] = round(time.perf_counter() - started, 3)
    result['limits'] = 'Tiny synthetic Korean corpus; real parser/SQLite/Chroma/GGUF; no UI, GPT judgment or Windows validation.'
    (args.data_dir / f'{args.stage}-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
