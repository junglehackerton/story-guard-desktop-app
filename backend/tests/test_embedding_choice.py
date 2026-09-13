from backend.app.services.embedding_models import GEMMA_MODEL, GemmaEmbeddings, _LocalGemmaEmbeddings

def test_gemma_identity_and_batching(tmp_path, monkeypatch):
 import numpy as np
 model=_LocalGemmaEmbeddings(model_dir=tmp_path)
 class Fake:
  max_seq_length=2048
  prompts={'document':'d: ','query':'q: '}
  tokenizer=lambda self,text,**kw:{'input_ids':[1,2]}
  def encode_document(self,texts,**kwargs):
   assert kwargs['batch_size']==4
   return np.tile(np.ones(768)/np.sqrt(768),(len(texts),1))
  def encode_query(self,text,**kwargs):return np.ones(768)/np.sqrt(768)
 monkeypatch.setattr(model,'_model',lambda:Fake())
 assert len(model.embed_documents(['a','b']))==2
 assert len(model.embed_query('a'))==768
 assert GEMMA_MODEL in model.identity()


def test_gemma_batch_size_can_be_tuned_with_safe_cap(tmp_path, monkeypatch):
 import numpy as np
 model=_LocalGemmaEmbeddings(model_dir=tmp_path)
 calls=[]
 class Fake:
  max_seq_length=2048
  prompts={'document':'d: ','query':'q: '}
  tokenizer=lambda self,text,**kw:{'input_ids':[1,2]}
  def encode_document(self,texts,**kwargs):
   calls.append(kwargs['batch_size'])
   return np.tile(np.ones(768)/np.sqrt(768),(len(texts),1))
  def encode_query(self,text,**kwargs): return np.ones(768)/np.sqrt(768)
 monkeypatch.setattr(model,'_model',lambda:Fake())
 monkeypatch.setenv('STORY_GUARD_EMBED_BATCH','99')
 model.embed_documents(['a'])
 assert calls == [8]


def test_gemma_worker_cleanup_terminates_live_processes():
 class Process:
  def __init__(self): self.terminated = False; self.killed = False
  def poll(self): return None
  def terminate(self): self.terminated = True
  def wait(self, timeout): return 0
  def kill(self): self.killed = True
 process = Process()
 GemmaEmbeddings._workers = {'test': process}
 GemmaEmbeddings._cleanup_workers()
 assert process.terminated is True
 assert GemmaEmbeddings._workers == {}
