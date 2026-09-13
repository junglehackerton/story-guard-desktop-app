"""Measure GPT request reduction when a long manuscript grows or changes."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))

from backend.app.database import Database
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer
from backend.app.repository import StoryRepository
from backend.app.services.rag import RagService

source = root / "output/validation/realistic-manuscript-20260912/manuscripts.json"
manuscripts = json.loads(source.read_text())
splitter = RagService.__new__(RagService)


class RagStub:
    def __init__(self, repository):
        self.repository = repository

    def sync_project(self, project_id, progress=None):
        rows = self.repository.list_chunks(project_id)
        if progress:
            progress(len(rows), len(rows))
        return len(rows)

    def retrieve(self, project_id, query, limit=4, strategy="hybrid"):
        return []


with tempfile.TemporaryDirectory(prefix="storyguard-incremental-") as directory:
    repo = StoryRepository(Database(Path(directory) / "review.sqlite"))
    project = repo.create_project("증분 분석 요청 수 검증")
    for chapter, text in sorted(manuscripts.items(), key=lambda item: int(item[0])):
        doc = repo.add_document(project.id, Path(directory) / f"{chapter}.txt", f"{chapter}화", "txt", chapter, text, int(chapter) - 1)
        chunks = splitter.split_text(text, doc.id, project.id)
        repo.replace_chunks(project.id, doc.id, [chunk.text for chunk in chunks])

    calls = []

    def complete(model, prompt, **kwargs):
        calls.append(prompt)
        return {"text": '{"entities": [], "relations": [], "issues": []}'}

    analyzer = GptStoryAnalyzer(repo, RagStub(repo), SimpleNamespace(complete=complete))
    first = analyzer.analyze(project.id, "GPT-6.5-Luna", "medium")
    initial_calls = len(calls)

    chapter = repo.add_document(project.id, Path(directory) / "11.txt", "11화", "txt", "11", "새 회차의 사건이 시작된다. " * 1200, 10)
    chunks = splitter.split_text(chapter.content, chapter.id, project.id)
    repo.replace_chunks(project.id, chapter.id, [chunk.text for chunk in chunks])
    before_append = len(calls)
    appended = analyzer.analyze(project.id, "GPT-6.5-Luna", "medium")
    append_calls = len(calls) - before_append

    first_doc = repo.list_documents(project.id)[0]
    repo.replace_chunks(project.id, first_doc.id, ["수정된 회차에서 새로운 사실이 드러난다."])
    before_edit = len(calls)
    edited = analyzer.analyze(project.id, "GPT-6.5-Luna", "medium")
    edit_calls = len(calls) - before_edit

    report = {
        "initial_chapters": 10,
        "initial_chars": sum(len(text) for text in manuscripts.values()),
        "initial_provider_calls": initial_calls,
        "after_append_chapters": 11,
        "append_provider_calls": append_calls,
        "append_cached_windows": appended["cached_count"],
        "after_edit_provider_calls": edit_calls,
        "edit_cached_windows": edited["cached_count"],
        "expected_behavior": "새 회차는 새 검토 구간만, 수정은 변경된 구간만 요청",
    }
    output = root / "output/validation/realistic-manuscript-20260912/incremental.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
