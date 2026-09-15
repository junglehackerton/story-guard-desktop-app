import json
from types import SimpleNamespace

from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer


def test_single_passage_candidate_survives_without_conflict_and_old_cache_is_replaced(tmp_path):
    repo = StoryRepository(Database(tmp_path / 'test.sqlite'))
    project = repo.create_project('단서 검토')
    text = '봉투에는 자정에 탑으로 오면 발신자를 만날 수 있다고 쓰여 있었다.'
    doc = repo.add_document(project.id, tmp_path / 'one.txt', '1화', 'txt', 'one', text, 0)
    chunk_id = repo.replace_chunks(project.id, doc.id, [text])[0]
    rag = SimpleNamespace(sync_project=lambda _: 1, retrieve=lambda *a, **k: [])
    calls = []
    payload = {'entities': [], 'relations': [], 'issues': []}

    def complete(*args, **kwargs):
        calls.append(args)
        return {'text': json.dumps(payload, ensure_ascii=False)}

    analyzer = GptStoryAnalyzer(repo, rag, SimpleNamespace(complete=complete))
    analyzer.REVIEW_VERSION = 'gpt-review-v4-split'
    analyzer.analyze(project.id, 'model', 'low')
    assert not repo.graph(project.id).entities

    analyzer.REVIEW_VERSION = GptStoryAnalyzer.REVIEW_VERSION
    payload['entities'] = [
        {'id': 'envelope', 'type': 'item', 'name': '봉투', 'summary': '만남을 알린 봉투',
         'evidence': [{'chunk_id': chunk_id, 'quote': text}]},
        {'id': 'sender', 'type': 'foreshadowing', 'name': '봉투 발신자의 정체',
         'summary': '탑에서 발신자를 만날 수 있다는 약속. 회수 여부는 확인 필요.',
         'evidence': [{'chunk_id': chunk_id, 'quote': text}]},
    ]
    result = analyzer.analyze(project.id, 'model', 'low')
    assert result['published'] and result['request_count'] == 1 and result['cached_count'] == 0
    assert result['issue_count'] == 0
    graph = repo.graph(project.id)
    assert {e.type for e in graph.entities} == {'item', 'foreshadowing'}
    candidate = next(e for e in graph.entities if e.type == 'foreshadowing')
    assert candidate.document_ids == [doc.id]
    repo.set_foreshadowing_status(project.id, candidate.id, 'in_progress')
    again = analyzer.analyze(project.id, 'model', 'low')
    assert again['cached_count'] == 1 and len(calls) == 2
    assert repo.list_foreshadowing_statuses(project.id)[0].status == 'in_progress'
