import uuid
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from backend.app import demo_server as server

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('STORY_GUARD_DEMO_USAGE_DB',str(tmp_path/'usage.sqlite'))
    monkeypatch.setenv('STORY_GUARD_DEMO_OPENAI_API_KEY','test-key')
    monkeypatch.setenv('STORY_GUARD_DEMO_INPUT_USD_PER_M','1')
    monkeypatch.setenv('STORY_GUARD_DEMO_OUTPUT_USD_PER_M','2')
    monkeypatch.setenv('STORY_GUARD_DEMO_KRW_PER_USD','1500')
    index=tmp_path/'index.npz';index.touch()
    monkeypatch.setattr(server,'index_path',lambda:index)
    class Index:
        def search(self,text,end): return [dict(id=1,document_id=1,text='근거 원문',chapter_index=0)]
    monkeypatch.setattr(server,'get_index',lambda:Index())
    class Provider:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):
            class Result:
                def raise_for_status(self):pass
                def json(self):return {'output':[{'content':[{'type':'output_text','text':'{"verdict":"conflict","summary":"설정 확인이 필요합니다.","evidence_ids":[1]}'}]}],'usage':{'input_tokens':20,'output_tokens':20}}
            return Result()
    monkeypatch.setattr(server.httpx,'Client',Provider)
    c=TestClient(server.app);c.get('/api/demo/status');return c

def payload(**kwargs):
    value=dict(text='새 문장',end_chapter=2,version=server.sample['version'],request_id=str(uuid.uuid4()))
    value.update(kwargs)
    return value

def test_quota_is_persistent_and_duplicate_is_not_charged(client):
    p=payload()
    assert client.post('/api/demo/analyze',json=p).json()['remaining']==2
    assert client.post('/api/demo/analyze',json=p).status_code==409
    assert client.post('/api/demo/analyze',json=payload()).status_code==200
    assert client.post('/api/demo/analyze',json=payload()).json()['remaining']==0
    assert client.post('/api/demo/analyze',json=payload()).status_code==429
    assert client.get('/api/demo/status').json()['remaining']==0
    with server.db() as c:assert c.execute('select count(*) from calls').fetchone()[0]==3

def test_budget_and_missing_key(client,monkeypatch):
    monkeypatch.setenv('STORY_GUARD_DEMO_BUDGET_KRW','0.001')
    assert client.post('/api/demo/analyze',json=payload()).status_code==429
    monkeypatch.delenv('STORY_GUARD_DEMO_OPENAI_API_KEY')
    assert client.get('/api/demo/status').json()['ready'] is False
    assert client.post('/api/demo/analyze',json=payload()).status_code==503

def test_version_range_and_empty_input(client):
    p=payload();p['version']='old'
    assert client.post('/api/demo/analyze',json=p).status_code==409
    p=payload();p['end_chapter']=100
    assert client.post('/api/demo/analyze',json=p).status_code==422
    p=payload();p['text']=' '
    assert client.post('/api/demo/analyze',json=p).status_code==422

def test_invalid_evidence_is_rejected():
    with pytest.raises(ValueError):
        server.parse_result({'output':[{'content':[{'type':'output_text','text':'{"verdict":"conflict","summary":"test","evidence_ids":[999]}'}]}]},[{'id':1}])

def test_busy_does_not_consume_quota(client):
    acquired=[server.analysis_slots.acquire() for _ in range(4)]
    try:assert client.post('/api/demo/analyze',json=payload()).status_code==429
    finally:
        for _ in acquired: server.analysis_slots.release()
    assert client.get('/api/demo/status').json()['remaining']==3

def test_four_visitors_can_analyze_independently(client,monkeypatch):
    """The public demo accepts four overlapping visitors without sharing results."""
    seen=[]
    class SlowProvider:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):
            time.sleep(0.15)
            seen.append(kwargs.get('json',{}).get('input',''))
            class Result:
                def raise_for_status(self):pass
                def json(self):return {'output':[{'content':[{'type':'output_text','text':'{"verdict":"conflict","summary":"개별 결과","evidence_ids":[1]}'}]}],'usage':{'input_tokens':20,'output_tokens':20}}
            return Result()
    monkeypatch.setattr(server.httpx,'Client',SlowProvider)
    visitors=[TestClient(server.app) for _ in range(4)]
    for visitor in visitors: visitor.get('/api/demo/status')
    texts=[f'방문자 {i}의 새 문장' for i in range(4)]
    def submit(item):
        i,visitor=item
        result=visitor.post('/api/demo/analyze',json=payload(text=texts[i]))
        return result.status_code,result.json()['remaining']
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(submit,enumerate(visitors)))
    assert results==[(200,2)]*4
    assert len(seen)==4

def test_fifth_overlapping_request_is_rejected_without_reservation(client):
    acquired=[server.analysis_slots.acquire() for _ in range(4)]
    try:
        response=client.post('/api/demo/analyze',json=payload())
        assert response.status_code==429
        assert client.get('/api/demo/status').json()['remaining']==3
        with server.db() as connection:
            assert connection.execute('select count(*) from calls').fetchone()[0]==0
    finally:
        for _ in acquired: server.analysis_slots.release()

def test_private_desktop_routes_are_not_exposed(client):
    assert client.post('/projects',json={'title':'x'}).status_code in (404,405)
    assert client.post('/api/chatgpt/login').status_code in (404,405)

def test_failure_reserves_uncertain_cost_without_saving_text(client,monkeypatch):
    class Failed:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):raise RuntimeError('network unavailable')
    monkeypatch.setattr(server.httpx,'Client',Failed)
    p=payload()
    assert client.post('/api/demo/analyze',json=p).status_code==502
    assert client.post('/api/demo/analyze',json=p).status_code==409
    with server.db() as c:
        row=dict(c.execute('SELECT * FROM calls').fetchone())
        assert row['cost']>0 and row['state']=='uncertain'
        assert p['text'] not in str(row)
    assert client.get('/api/demo/status').json()['remaining']==3

def test_new_day_restores_allowance(client,monkeypatch):
    for _ in range(3):assert client.post('/api/demo/analyze',json=payload()).status_code==200
    monkeypatch.setattr(server,'today',lambda:'2099-01-01')
    assert client.get('/api/demo/status').json()['remaining']==3

def test_retrieval_failure_refunds_reservation(client,monkeypatch):
    def fail():raise RuntimeError('model missing')
    monkeypatch.setattr(server,'get_index',fail)
    p=payload()
    assert client.post('/api/demo/analyze',json=p).status_code==502
    with server.db() as c:
        row=c.execute('SELECT state,cost FROM calls').fetchone()
        assert row['state']=='failed' and row['cost']==0
