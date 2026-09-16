"""Portable Qwen index: precompute sample passages, embed only queries at runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import numpy as np
from backend.app.services.local_ai import LocalLlmEmbeddings, DEFAULT_EMBEDDING_MODEL, QUERY_INSTRUCTION, resolve_model_path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / 'src/demo/snapshot.json'

def index_path():
    return Path(os.getenv('STORY_GUARD_DEMO_INDEX', str(ROOT / 'output/web-demo/index.npz')))

def embedder():
    directory = os.getenv('STORY_GUARD_DEMO_MODEL_DIR')
    return LocalLlmEmbeddings(DEFAULT_EMBEDDING_MODEL, Path(directory) if directory else None)

def model_hash(model):
    path = resolve_model_path(model.model, model.model_dir)
    if path is None:
        raise RuntimeError('Qwen 임베딩 모델이 없습니다.')
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def build():
    sample = json.loads(SNAPSHOT.read_text())
    model = embedder()
    rows = []
    for document in sample['documents']:
        text = document['content']
        # Short overlapping exact excerpts stay inside the Korean model context.
        for start in range(0, len(text), 140):
            excerpt = text[start:start+180]
            if excerpt.strip():
                rows.append(dict(id=len(rows)+1, document_id=document['id'], chapter_index=document['chapter_index'], start_offset=start, text=excerpt))
    vectors = []
    for start in range(0, len(rows), 16):
        vectors.extend(model.embed_documents([r['text'] for r in rows[start:start+16]]))
        print(f'Indexed {min(start+16,len(rows))}/{len(rows)} passages', flush=True)
    target = index_path()
    target.parent.mkdir(parents=True,exist_ok=True)
    temp = target.with_suffix('.tmp.npz')
    np.savez_compressed(temp, vectors=np.asarray(vectors,dtype=np.float32), rows=json.dumps(rows,ensure_ascii=False),
        version=sample['version'], model_hash=model_hash(model), instruction=QUERY_INSTRUCTION)
    temp.replace(target)
    print(f'Saved {len(rows)} passages: {target}')

class DemoIndex:
    def __init__(self):
        self.model = embedder()
        sample = json.loads(SNAPSHOT.read_text())
        with np.load(index_path(),allow_pickle=False) as data:
            if str(data['version']) != sample['version'] or str(data['instruction']) != QUERY_INSTRUCTION or str(data['model_hash']) != model_hash(self.model):
                raise RuntimeError('샘플 또는 임베딩 모델이 변경되었습니다. 인덱스를 다시 준비하세요.')
            self.rows = json.loads(str(data['rows']))
            self.vectors = data['vectors'].copy()
        self.documents = {d['id']: d['content'] for d in sample['documents']}
        self.vectors /= np.maximum(np.linalg.norm(self.vectors,axis=1,keepdims=True),1e-12)

    def search(self, text, end_chapter):
        vector = np.asarray(self.model.embed_query(text),dtype=np.float32)
        vector /= max(float(np.linalg.norm(vector)),1e-12)
        scores = self.vectors @ vector
        eligible = [i for i,r in enumerate(self.rows) if r['chapter_index'] <= end_chapter]
        ranked = sorted(eligible,key=lambda i:float(scores[i]),reverse=True)
        selected = []
        for i in ranked:
            row = self.rows[i]
            # Avoid adjacent, largely overlapping search hits consuming the context.
            if any(r['document_id']==row['document_id'] and abs(r['id']-row['id'])<=1 for r in selected):
                continue
            selected.append(row)
            if len(selected)==8: break
        # Include surrounding dialogue so speaker/age/state references stay interpretable.
        expanded = []
        for row in selected:
            source = self.documents[row['document_id']]
            start = row.get('start_offset', source.find(row['text']))
            if start < 0: raise RuntimeError('Search excerpt does not match sample')
            expanded.append({**row, 'text': source[max(0,start-220):start+len(row['text'])+220]})
        return expanded

if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    build()
