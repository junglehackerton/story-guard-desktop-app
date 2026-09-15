import json
from types import SimpleNamespace
import pytest
from backend.tests.test_gpt_analysis import fixture
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer


def test_revision_preserves_identity_and_history_and_removes_old_chunks(tmp_path):
    repo, project, ids, rag = fixture(tmp_path)
    doc = repo.list_documents(project.id)[0]
    issue = repo.add_issue(project.id, 'high', 'contradiction', '계약 충돌', '조건 위반', ids)
    repo.update_issue_status(issue.id, 'ignored')
    revised = repo.replace_document(doc.id, tmp_path/'revised.txt', 'txt', 'new-hash', '유나는 정식 계약을 맺었다.', ['유나는 정식 계약을 맺었다.'])
    assert revised.id == doc.id and revised.chapter_index == doc.chapter_index
    assert revised.content_hash == 'new-hash'
    assert not repo.get_chunks(ids)
    assert repo.graph(project.id).issues == []
    history = repo.review_history(project.id)
    assert history[0]['status'] == 'ignored'
    assert history[0]['outcome'] == 'pending'
    assert history[0]['evidence'][0]['text'] == '계약자만 검을 쓴다.'


def test_append_preserves_decision_and_successful_reanalysis_restores_it(tmp_path):
    repo, project, ids, rag = fixture(tmp_path)
    issue = repo.add_issue(project.id, 'low', 'contradiction', '작가 판단', '유지', ids)
    repo.update_issue_status(issue.id, 'deferred')
    doc = repo.add_document(project.id, tmp_path/'next.txt', '다음 회차', 'txt', 'next', '다음 날이었다.', 1)
    repo.replace_chunks(project.id, doc.id, ['다음 날이었다.'])
    assert repo.review_history(project.id)[0]['status'] == 'deferred'
    payload = {'entities': [], 'relations': [], 'issues': [{'title':'같은 충돌','description':'계속 남음','severity':'high','evidence_chunk_ids':ids}]}
    GptStoryAnalyzer(repo, rag, SimpleNamespace(complete=lambda *a,**k: {'text':json.dumps(payload)})).analyze(project.id,'model','low')
    assert repo.graph(project.id).issues[0].status == 'deferred'
    assert repo.review_history(project.id)[0]['outcome'] == 'redetected'


def test_failed_analysis_does_not_claim_resolution(tmp_path):
    repo, project, ids, rag = fixture(tmp_path)
    repo.add_issue(project.id, 'high', 'contradiction', '이전 충돌', '후보', ids)
    repo.add_document(project.id, tmp_path/'new.txt', '추가', 'txt', 'new', '추가', 1)
    result = GptStoryAnalyzer(repo,rag,SimpleNamespace(complete=lambda *a,**k:{'text':'invalid'})).analyze(project.id,'model',None)
    assert result['published'] is False
    assert result['failed_window_count'] > 0
    assert repo.review_history(project.id)[0]['outcome'] == 'pending'


def test_successful_empty_result_records_not_redetected_not_resolved(tmp_path):
    repo, project, ids, rag = fixture(tmp_path)
    repo.add_issue(project.id, 'high', 'contradiction', '이전 충돌', '후보', ids)
    repo.add_document(project.id, tmp_path/'new.txt', '추가', 'txt', 'new', '추가', 1)
    GptStoryAnalyzer(repo,rag,SimpleNamespace(complete=lambda *a,**k:{'text':'{"entities":[],"relations":[],"issues":[]}'})).analyze(project.id,'model',None)
    assert repo.review_history(project.id)[0]['outcome'] == 'not_redetected'


def test_same_content_replacement_keeps_existing_results(tmp_path):
    repo, project, ids, rag = fixture(tmp_path)
    doc = repo.list_documents(project.id)[0]
    issue = repo.add_issue(project.id, 'low', 'contradiction', '동일 내용', '유지', ids)
    repo.replace_document(doc.id,tmp_path/'same.txt','txt',doc.content_hash,doc.content,['unused'])
    assert repo.graph(project.id).issues[0].id == issue.id
    assert len(repo.get_chunks(ids)) == 2
    assert not repo.review_history(project.id)


def test_revised_manuscript_is_stale_without_reusing_previous_analysis(tmp_path):
    repo, project, ids, rag = fixture(tmp_path)
    doc = repo.list_documents(project.id)[0]
    repo.upsert_document_analysis_cache(doc.id, project.id, doc.content_hash, {'previous': True})
    assert repo.list_documents(project.id)[0].analysis_status == 'analyzed'

    repo.replace_document(doc.id, tmp_path/'revised.txt', 'txt', 'changed', '수정한 원고', ['수정한 원고'])

    revised = repo.list_documents(project.id)[0]
    assert revised.analysis_status == 'stale'
    assert revised.analyzed_at is not None
    assert repo.get_document_analysis_cache(doc.id, revised.content_hash) is None
    assert not repo.get_chunks(ids)


def test_replace_rolls_back_all_data_if_chunk_write_fails(tmp_path, monkeypatch):
    repo, project, ids, rag = fixture(tmp_path)
    doc = repo.list_documents(project.id)[0]
    issue = repo.add_issue(project.id, 'low', 'contradiction', '유지', '유지', ids)
    def fail(*args, **kwargs): raise RuntimeError('disk failure')
    monkeypatch.setattr(repo, 'replace_chunks', fail)
    with pytest.raises(RuntimeError): repo.replace_document(doc.id,tmp_path/'new.txt','txt','changed','수정',['수정'])
    assert repo.list_documents(project.id)[0].content == doc.content
    assert repo.graph(project.id).issues[0].id == issue.id
    assert len(repo.get_chunks(ids)) == 2
    assert not repo.review_history(project.id)


def test_replace_api_rejects_empty_and_missing_file(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import main
    repo, project, ids, rag = fixture(tmp_path)
    monkeypatch.setattr(main, 'repository', repo)
    doc = repo.list_documents(project.id)[0]
    client = TestClient(main.app)
    empty = tmp_path/'empty.txt';empty.write_text('')
    assert client.put(f'/documents/{doc.id}',json={'path':str(empty)}).status_code == 400
    assert client.put(f'/documents/{doc.id}',json={'path':str(tmp_path/'missing.txt')}).status_code == 404
    assert len(repo.get_chunks(ids)) == 2
    valid = tmp_path/'valid.txt';valid.write_text('유나는 계약을 맺었다.')
    response = client.put(f'/documents/{doc.id}',json={'path':str(valid)})
    assert response.status_code == 200 and response.json()['id'] == doc.id
    assert response.json()['chapter_index'] == doc.chapter_index


@pytest.mark.parametrize('status', ['accepted', 'ignored', 'deferred', 'open'])
def test_judgment_changes_persist_without_reanalysis_and_can_be_reopened(tmp_path, status):
    repo, project, ids, rag = fixture(tmp_path)
    issue = repo.add_issue(project.id, 'high', 'contradiction', '판단 변경', '근거', ids)
    repo.update_issue_status(issue.id, status)
    from backend.app.repository import StoryRepository
    reopened = StoryRepository(repo.database)
    assert reopened.graph(project.id).issues[0].status == status
    assert not reopened.review_history(project.id)
    assert reopened.latest_analysis_job(project.id) is None
    reopened.update_issue_status(issue.id, 'open')
    assert repo.graph(project.id).issues[0].status == 'open'


@pytest.mark.parametrize('status', ['accepted', 'ignored', 'deferred'])
def test_reanalysis_keeps_latest_author_decision(tmp_path, status):
    repo, project, ids, rag = fixture(tmp_path)
    issue = repo.add_issue(project.id, 'high', 'contradiction', '판단 변경', '근거', ids)
    repo.update_issue_status(issue.id, 'accepted')
    repo.update_issue_status(issue.id, status)
    payload = {'entities': [], 'relations': [], 'issues': [{'title':'같은 후보','description':'근거 동일','severity':'high','evidence_chunk_ids':ids}]}
    GptStoryAnalyzer(repo, rag, SimpleNamespace(complete=lambda *a,**k: {'text':json.dumps(payload)})).analyze(project.id,'model','low')
    assert repo.graph(project.id).issues[0].status == status
