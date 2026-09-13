import json
from types import SimpleNamespace

import pytest

from backend.app.database import Database
from backend.app.models import AnalysisStatus
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer
from backend.app.repository import StoryRepository


@pytest.mark.parametrize('stop', ['restart', 'cancel', 'failure'])
def test_stopping_analysis_closes_only_unfinished_windows(tmp_path, stop):
    repo = StoryRepository(Database(tmp_path / 'stop.sqlite'))
    project = repo.create_project('중단 기록 검증')
    job = repo.create_running_analysis_job(project.id, '3번째 구간', 'gpt_wait', 42)
    details = [dict(index=i + 1, chunk_id=i + 1, document=f'{i + 1}화', status=status,
                    stage='wait', attempts=1, elapsed_seconds=12, error='')
               for i, status in enumerate(['completed', 'failed', 'running', 'queued'])]
    details[1]['error'] = '기존 시간 초과'
    details[2]['parts'] = [dict(path='L', chunk_ids=[3], status='completed', reused=True),
                           dict(path='R', chunk_ids=[4], status='running', stage='wait', attempts=2)]
    context = {'model': 'luna', 'effort': 'medium'}
    checkpoints = json.dumps({'0': {'response': '저장된 성공 응답'}})
    with repo.database.connect() as db:
        db.execute('UPDATE analysis_jobs SET window_details=?,review_context=? WHERE id=?',
                   (json.dumps(details), json.dumps(context), job.id))
        db.execute('INSERT INTO gpt_review_runs(job_id,project_id,snapshot_key,checkpoints) VALUES(?,?,?,?)',
                   (job.id, project.id, 'snapshot', checkpoints))
    if stop == 'restart':
        assert repo.mark_running_jobs_interrupted() == 1
        assert repo.mark_running_jobs_interrupted() == 0
    elif stop == 'cancel':
        repo.cancel_analysis(project.id, preserve_results=True)
    else:
        repo.update_running_job(job.id, AnalysisStatus.failed, '원고가 변경되었습니다.', current_step='failed')
    ended = repo.get_job(job.id)
    assert ended.progress == 42
    assert [item['status'] for item in ended.window_details] == ['completed', 'failed', 'interrupted', 'deferred']
    assert ended.window_details[1] == details[1]
    active = ended.window_details[2]
    assert active['stage'] == 'wait' and active['attempts'] == 1 and active['elapsed_seconds'] == 12
    assert active['error']
    assert active['parts'][0] == details[2]['parts'][0]
    assert active['parts'][1]['status'] == 'interrupted'
    assert active['parts'][1]['stage'] == 'wait'
    assert ended.review_context == context
    with repo.database.connect() as db:
        assert db.execute('SELECT checkpoints FROM gpt_review_runs WHERE job_id=?', (job.id,)).fetchone()[0] == checkpoints
    # A late worker update must not revive the stopped job or erase diagnostics.
    repo.update_running_job(job.id, AnalysisStatus.running, '늦게 도착한 진행', progress=90)
    assert repo.get_job(job.id).model_dump() == ended.model_dump()


def test_index_failure_retains_selected_gpt_model_before_any_request(tmp_path):
    repo = StoryRepository(Database(tmp_path / 'index.sqlite'))
    project = repo.create_project('검색 준비 실패')
    doc = repo.add_document(project.id, tmp_path / 'story.txt', '등대', 'txt', 'hash', '서아는 등대를 지켰다.', 0)
    repo.replace_chunks(project.id, doc.id, ['서아는 등대를 지켰다.'])
    def fail_index(*args, **kwargs):
        context = repo.latest_analysis_job(project.id).review_context
        assert context['model'] == 'luna' and context['effort'] == 'medium'
        assert context['start_chapter'] is None and context['end_chapter'] is None
        raise RuntimeError('검색 모델을 열 수 없습니다.')
    rag = SimpleNamespace(repository=None, sync_project=fail_index)
    with pytest.raises(RuntimeError, match='검색 모델'):
        GptStoryAnalyzer(repo, rag, SimpleNamespace()).analyze(project.id, 'luna', 'medium')
    job = repo.latest_analysis_job(project.id)
    assert job.status == AnalysisStatus.failed and job.progress == 5
    assert job.review_context['model'] == 'luna'
    assert job.review_context['effort'] == 'medium'


def test_process_interruption_resumes_durable_successes(tmp_path):
    database_path = tmp_path / 'resume.sqlite'
    repo = StoryRepository(Database(database_path))
    project = repo.create_project('중단 후 이어서 검토')
    for index in range(3):
        text = f'{index + 1}화. 서아는 등대의 기록을 읽었다.'
        doc = repo.add_document(project.id, tmp_path / f'{index}.txt', f'기록 {index + 1}', 'txt', str(index), text, index)
        repo.replace_chunks(project.id, doc.id, [text])
    rag = SimpleNamespace(sync_project=lambda *a, **k: 3, retrieve=lambda *a, **k: [])
    class ProcessStopped(BaseException):
        pass
    calls = []
    def complete(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            raise ProcessStopped()
        return {'text': '{"entities":[],"relations":[],"issues":[]}'}
    with pytest.raises(ProcessStopped):
        GptStoryAnalyzer(repo, rag, SimpleNamespace(complete=complete)).analyze(project.id, 'luna', 'medium', force=True)
    old_job = repo.latest_analysis_job(project.id)
    restarted = StoryRepository(Database(database_path))
    restarted.mark_running_jobs_interrupted()
    assert [row['status'] for row in restarted.get_job(old_job.id).window_details] == ['completed', 'interrupted', 'deferred']
    retry_calls = []
    def recovered(model, prompt, **kwargs):
        assert model == 'luna' and kwargs['effort'] == 'medium'
        retry_calls.append(prompt)
        return {'text': '{"entities":[],"relations":[],"issues":[]}'}
    result = GptStoryAnalyzer(restarted, rag, SimpleNamespace(complete=recovered)).analyze(project.id, 'luna', 'medium')
    assert len(retry_calls) == 2 and result['cached_count'] == 1
    assert result['published'] is True
