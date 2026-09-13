from backend.app.services.hybrid_search import lexical_rank, merge_rankings

def test_rare_rule_survives_long_distractor_paragraph():
 rows=[{'chunk_id':1,'text':'항구 소문과 날씨 이야기. '*80+'\n\n전령은 붉은 인장이 찍힌 편지만 국경 밖으로 운반한다.'}, {'chunk_id':2,'text':'편지 국경 소문. '*100}]
 assert lexical_rank(rows,'국경을 넘는 편지에 필요한 인장')[0]['chunk_id']==1

def test_merge_keeps_both_sources_without_duplicates_or_extra_context():
 rows=[{'chunk_id':i,'text':str(i)} for i in range(6)]
 got=merge_rankings(rows, [rows[0],rows[4],rows[5]],4)
 assert [r['chunk_id'] for r in got]==[0,1,4,2]
 assert len(merge_rankings(rows,[],1))==1
 assert merge_rankings(rows,rows,0)==[]

def test_merge_normalizes_dense_and_lexical_chunk_id_types():
 rows=[{'chunk_id':1,'text':'규칙 근거'}]
 lexical=[{'chunk_id':'1','text':'같은 규칙 근거'}]
 got=merge_rankings(rows, lexical, 1)
 assert len(got)==1

def test_no_keyword_match_does_not_invent_lexical_hits():
 assert lexical_rank([{'chunk_id':1,'text':'사과 바나나'}],'봉인검 계약')==[]

def test_hybrid_retrieval_respects_chapters_and_projects(tmp_path, monkeypatch):
 from backend.app.services import rag as module
 from backend.tests.test_rag import TinyEmbeddings
 monkeypatch.setattr(module,'LocalLlmEmbeddings',TinyEmbeddings)
 rag=module.RagService(tmp_path,embedding_model='test')
 rag.index_chunks(1,[1,2],['붉은 인장 계약','편지 일반 규칙'],document_id=1,chapter_index=0)
 rag.index_chunks(1,[3],['붉은 인장 비밀 계약'],document_id=2,chapter_index=8)
 rag.index_chunks(2,[4],['붉은 인장 다른 작품 계약'],document_id=3,chapter_index=0)
 hits=rag.retrieve(1,'붉은 인장 계약',limit=4,end_chapter=0,strategy='hybrid')
 assert {r['chunk_id'] for r in hits}=={1,2}
 assert all(r['project_id']==1 and r['chapter_index']==0 for r in hits)
