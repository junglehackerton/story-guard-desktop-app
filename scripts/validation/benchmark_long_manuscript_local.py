"""Measure local indexing/retrieval on the 10 x 15k-character fixture."""
from __future__ import annotations
import json, resource, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import os
os.environ['STORY_GUARD_DATA_DIR'] = '/tmp/storyguard-long-local-20260913'
from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.services.rag import RagService
from backend.app.services.embedding_models import GEMMA_MODEL

fixture = ROOT / 'output/validation/long-manuscript-20260913/episodes'
data = Path('/tmp/storyguard-long-local-20260913')
import shutil
shutil.rmtree(data, ignore_errors=True)
data.mkdir(parents=True)
(data / 'models' / GEMMA_MODEL).parent.mkdir(parents=True, exist_ok=True)
(data / 'models' / GEMMA_MODEL).symlink_to(ROOT / '.cache/embedding-bench-models' / GEMMA_MODEL)
repo = StoryRepository(Database(data / 'story.sqlite'))
project = repo.create_project('장편 10회 로컬 부하 검증')
splitter = RagService.__new__(RagService)
for index, path in enumerate(sorted(fixture.glob('episode-*.txt'))):
    text = path.read_text(encoding='utf-8')
    doc = repo.add_document(project.id, path, f'{index+1}화', 'txt', str(path.stat().st_mtime_ns), text, index)
    repo.replace_chunks(project.id, doc.id, [c.text for c in splitter.split_text(text, doc.id, project.id)])
rag = RagService(data / 'chroma', embedding_model=GEMMA_MODEL, repository=repo)
started = time.perf_counter()
rag.sync_project(project.id)
elapsed = time.perf_counter() - started
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024*1024 if sys.platform == 'darwin' else 1024)
result = {'episodes': 10, 'total_chars': sum(len(p.read_text(encoding='utf-8')) for p in fixture.glob('*.txt')), 'chunks': len(repo.list_chunks(project.id)), 'index_seconds': round(elapsed, 3), 'max_rss_mb': round(rss, 1), 'status': 'completed'}
out = ROOT / 'output/validation/long-manuscript-20260913/local-index.json'
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
