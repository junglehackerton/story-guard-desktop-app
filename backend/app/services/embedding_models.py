"""Optional EmbeddingGemma adapter, independent from llama.cpp generation."""
from pathlib import Path
import hashlib
import importlib.util
import threading
import os
import sys
import subprocess
import json
import atexit
from backend.app.config import models_path

GEMMA_MODEL = 'embeddinggemma-300m'
GEMMA_REVISION = '57c266a740f537b4dc058e1b0cda161fd15afa75'

def is_gemma_model(value: str | Path) -> bool:
    """Recognize the Gemma adapter from either its logical name or model path."""
    candidate = Path(str(value).strip()).name.lower()
    return candidate in {GEMMA_MODEL, f'{GEMMA_MODEL}.safetensors'}

def gemma_python():
    configured = os.getenv('STORY_GUARD_GEMMA_PYTHON')
    if configured:
        return Path(configured)
    runtime = models_path().parent / 'gemma-runtime'
    installed = runtime / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if installed.exists():
        return installed
    # Reuse the isolated evaluation environment in a development checkout only.
    return Path(__file__).resolve().parents[3] / '.cache/embedding-bench-venv/bin/python'

def gemma_runtime_ready():
    if os.getenv('STORY_GUARD_GEMMA_WORKER') == '1':
        return importlib.util.find_spec('sentence_transformers') is not None
    return gemma_python().is_file()

def gemma_ready(model_dir=None):
    directory = (model_dir or models_path()) / GEMMA_MODEL
    return gemma_runtime_ready() and all((directory / p).is_file() for p in
        ['config.json','modules.json','model.safetensors','tokenizer.json','2_Dense/model.safetensors','3_Dense/model.safetensors'])

def download_gemma(model_dir):
    if not gemma_runtime_ready():
        runtime = models_path().parent / 'gemma-runtime'
        if getattr(sys, 'frozen', False):
            raise RuntimeError('이 배포본에는 Gemma 실행 환경이 없습니다. Gemma 지원 배포본이 필요합니다.')
        subprocess.run([sys.executable, '-m', 'venv', str(runtime)], check=True)
        subprocess.run([str(gemma_python()), '-m', 'pip', 'install', '-r',
            str(Path(__file__).resolve().parents[2] / 'requirements-gemma.txt')], check=True)
    if os.getenv('STORY_GUARD_GEMMA_WORKER') != '1':
        subprocess.run([str(gemma_python()), '-m', 'backend.app.services.embedding_models', 'download', str(model_dir)], check=True, env={**os.environ, 'STORY_GUARD_GEMMA_WORKER':'1'}, cwd=Path(__file__).resolve().parents[3])
        return
    from huggingface_hub import snapshot_download
    try:
        snapshot_download('google/embeddinggemma-300m', revision=GEMMA_REVISION,
            local_dir=Path(model_dir)/GEMMA_MODEL,
            allow_patterns=['*.json','*.safetensors','tokenizer.model','README.md'])
    except Exception as error:
        if type(error).__name__ in {'GatedRepoError','LocalTokenNotFoundError'}:
            raise RuntimeError('Hugging Face에서 Gemma 이용 조건에 동의하고 hf auth login으로 연결해 주세요.') from error
        raise

class _LocalGemmaEmbeddings:
    _cache = {}
    _lock = threading.RLock()
    def __init__(self, model_dir=None):
        self.path = (model_dir or models_path()) / GEMMA_MODEL
    def identity(self):
        stamps = [(str(p.relative_to(self.path)),p.stat().st_size,p.stat().st_mtime_ns)
                  for p in sorted(self.path.rglob('*')) if p.is_file() and p.suffix in {'.json','.safetensors'} and '.cache' not in p.relative_to(self.path).parts]
        return GEMMA_MODEL+'-'+hashlib.sha256((str(self.path.resolve())+repr(stamps)+GEMMA_REVISION).encode()).hexdigest()[:20]
    def _model(self):
        if not gemma_ready(self.path.parent):
            raise RuntimeError('EmbeddingGemma 모델과 실행 환경 설치가 필요합니다.')
        key=self.identity()
        if key not in self._cache:
            import torch
            from sentence_transformers import SentenceTransformer
            device='cuda' if torch.cuda.is_available() else 'mps' if torch.backends.mps.is_available() else 'cpu'
            if device=='cpu':
                try:
                    torch.set_num_threads(max(1, min(int(os.getenv('STORY_GUARD_EMBED_THREADS', '4')), 4)))
                except ValueError:
                    torch.set_num_threads(4)
            requested_dtype = os.getenv('STORY_GUARD_GEMMA_DTYPE', 'float32').lower()
            low_memory = os.getenv('STORY_GUARD_LOW_MEMORY', '').lower() in {'1', 'true', 'yes'}
            # CPU float16 inference can produce invalid vectors with this
            # model, so keep the numerically safe dtype on CPU even when a
            # low-memory setting is requested.
            if device in {'mps', 'cuda'} and (requested_dtype == 'float16' or (requested_dtype == 'auto' and low_memory)):
                dtype = torch.float16
            elif device in {'mps', 'cuda'} and requested_dtype == 'bfloat16':
                dtype = torch.bfloat16
            else:
                dtype = torch.float32
            self._cache.clear()
            self._cache[key]=SentenceTransformer(str(self.path),device=device,local_files_only=True,
                trust_remote_code=False,model_kwargs={'torch_dtype':dtype})
        return self._cache[key]
    def _validate(self, model, texts, kind):
        for text in texts:
            count=len(model.tokenizer(model.prompts[kind]+text,truncation=False)['input_ids'])
            if count>min(2048,model.max_seq_length):
                raise ValueError('Gemma 입력이 2,048토큰을 초과했습니다. 원고를 더 짧게 나눠 주세요.')
    def embed_documents(self,texts):
        if not texts:return []
        with self._lock:
            model=self._model();self._validate(model,texts,'document')
            try:
                requested_batch = int(os.getenv('STORY_GUARD_EMBED_BATCH', '4'))
            except ValueError:
                requested_batch = 4
            batch_size = max(1, min(requested_batch, 8))
            while True:
                try:
                    values = model.encode_document(texts,batch_size=batch_size,show_progress_bar=False,convert_to_numpy=True)
                    return self._vectors(values)
                except (MemoryError, RuntimeError) as error:
                    message = str(error).lower()
                    if batch_size == 1 or not any(token in message for token in ('out of memory', 'memory', 'mps')):
                        raise
                    batch_size = max(1, batch_size // 2)
    def embed_query(self,text):
        with self._lock:
            model=self._model();self._validate(model,[text],'query')
            return self._vectors([model.encode_query(text,show_progress_bar=False,convert_to_numpy=True)])[0]
    def _vectors(self,values):
        import numpy as np
        array=np.asarray(values)
        if array.ndim!=2 or array.shape[1]!=768 or not np.isfinite(array).all():
            raise RuntimeError('Gemma가 올바른 768차원 임베딩을 반환하지 않았습니다.')
        return array.tolist()


class GemmaEmbeddings(_LocalGemmaEmbeddings):
    """One persistent isolated Python worker, reused across RAG service instances."""
    _workers = {}
    _cleanup_registered = False

    @classmethod
    def _cleanup_workers(cls):
        for process in list(cls._workers.values()):
            if process.poll() is not None:
                continue
            try:
                # Ask the isolated Python runtime to close its model and
                # multiprocessing resources before falling back to SIGTERM.
                stdin = getattr(process, 'stdin', None)
                if stdin is not None:
                    stdin.write(json.dumps({'kind': 'shutdown'}) + '\n')
                    stdin.flush()
                    process.wait(timeout=2)
                else:
                    process.terminate()
                    process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        cls._workers.clear()

    @classmethod
    def _ensure_cleanup_hook(cls):
        if not cls._cleanup_registered:
            atexit.register(cls._cleanup_workers)
            cls._cleanup_registered = True

    def _request(self, kind, texts):
        with self._lock:
            self._ensure_cleanup_hook()
            key = str(self.path.resolve())
            process = self._workers.get(key)
            if process is None or process.poll() is not None:
                process = subprocess.Popen([str(gemma_python()), '-m', 'backend.app.services.embedding_models', 'serve', str(self.path.parent)],
                    cwd=Path(__file__).resolve().parents[3], env={**os.environ,'STORY_GUARD_GEMMA_WORKER':'1'},
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
                self._workers[key] = process
            process.stdin.write(json.dumps({'kind':kind,'texts':texts})+'\n');process.stdin.flush()
            line = process.stdout.readline()
            if not line:
                raise RuntimeError('Gemma 실행 프로세스가 종료되었습니다.')
            result = json.loads(line)
            if 'error' in result:
                raise RuntimeError(result['error'])
            return result['vectors']
    def embed_documents(self, texts):
        return self._request('documents',texts) if texts else []
    def embed_query(self, text):
        return self._request('query',[text])[0]

if __name__ == '__main__':
    if sys.argv[1] == 'download':
        download_gemma(Path(sys.argv[2]))
    else:
        adapter = _LocalGemmaEmbeddings(Path(sys.argv[2]))
        for line in sys.stdin:
            try:
                request=json.loads(line)
                if request.get('kind') == 'shutdown':
                    break
                values=adapter.embed_documents(request['texts']) if request['kind']=='documents' else [adapter.embed_query(request['texts'][0])]
                result={'vectors':values}
            except Exception as error:
                result={'error':str(error)}
            print(json.dumps(result),flush=True)
