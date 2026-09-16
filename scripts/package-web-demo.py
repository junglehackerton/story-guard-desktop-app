"""Build a portable demo directory from an explicit allowlist, never a desktop DB."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'Qwen3-Embedding-0.6B-Q8_0.gguf'

def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source,'sha256').hexdigest()

def package(destination, model_dir, index):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError('Output already exists; choose a new directory to preserve previous releases.')
    snapshot = ROOT/'src/demo/snapshot.json'
    model = model_dir/MODEL
    if not (ROOT/'demo-dist/index.html').is_file() or not model.is_file():
        raise ValueError('Build the web demo and supply its Qwen model directory first.')
    sample = json.loads(snapshot.read_text())
    with np.load(index,allow_pickle=False) as saved:
        if str(saved['version']) != sample['version'] or str(saved['model_hash']) != digest(model):
            raise ValueError('Snapshot, model and embedding index do not match.')
    # The build contains the same immutable sample. Reject an old frontend.
    if not any(sample['version'] in p.read_text() for p in (ROOT/'demo-dist/assets').glob('*.js')):
        raise ValueError('The frontend build does not match the sample; rebuild it.')
    sources = [
        'backend/__init__.py','backend/app/__init__.py',
        'backend/app/demo_server.py','backend/app/demo_index.py',
        'backend/app/config.py','backend/app/models.py',
        'backend/app/services/local_ai.py',
        'backend/requirements-demo.txt','src/demo/snapshot.json',
    ]
    for name in sources:
        source = ROOT/name
        if not source.is_file(): raise ValueError(f'Missing source: {name}')
    destination.mkdir(parents=True)
    for name in sources:
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,target)
    shutil.copytree(ROOT/'demo-dist',destination/'demo-dist')
    (destination/'assets/models').mkdir(parents=True)
    shutil.copyfile(model,destination/'assets/models'/MODEL)
    shutil.copyfile(index,destination/'assets/index.npz')
    launcher=destination/'start.sh'
    launcher.write_text('''#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$base"
if [ "${DEMO_HOST:-127.0.0.1}" != "127.0.0.1" ] && [ "${DEMO_HOST:-127.0.0.1}" != "localhost" ]; then
  : "${STORY_GUARD_DEMO_USAGE_DB:?Set an explicit usage DB path on a persistent volume for public hosting}"
fi
export STORY_GUARD_DEMO_MODEL_DIR="$base/assets/models"
export STORY_GUARD_DEMO_INDEX="$base/assets/index.npz"
# Mount this directory on a persistent volume in production. Never delete it on redeploy.
export STORY_GUARD_DEMO_USAGE_DB="${STORY_GUARD_DEMO_USAGE_DB:-$base/state/usage.sqlite}"
exec "${DEMO_PYTHON:-python3}" -m uvicorn backend.app.demo_server:app --host "${DEMO_HOST:-127.0.0.1}" --port "${PORT:-4173}" --workers 1
''')
    launcher.chmod(0o755)
    (destination/'README.md').write_text('''# Story Guard standalone demo

Requires Python 3.11 and dependencies in `backend/requirements-demo.txt`.
Run `python3 -m pip install -r backend/requirements-demo.txt`, then `./start.sh`.
Set `DEMO_PYTHON` to select a virtualenv interpreter. The default bind is localhost.
For hosting set `DEMO_HOST=0.0.0.0`, `PORT`, and use an HTTPS reverse proxy.

Included: public sample, actual analysis results, Qwen model, precomputed vectors,
web build and minimal API code. No original desktop DB or login is required.
API credentials and pricing variables must be supplied by the deployment environment.
Without them the saved sample remains available; live GPT review stays disabled.

Set `STORY_GUARD_DEMO_USAGE_DB=/data/storyguard/usage.sqlite` on a persistent volume.
Back up that volume separately. Deployments replace the immutable application only.
This package contains no visitor usage DB, credentials, private desktop DB or auth cache.
Visitor judgments are browser-local; clearing browser storage resets those judgments.
''')
    manifest={'sample_version':sample['version'],'files':{}}
    for path in sorted(destination.rglob('*')):
        if path.is_file():manifest['files'][str(path.relative_to(destination))]={'sha256':digest(path),'bytes':path.stat().st_size}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model-dir',type=Path,required=True)
    parser.add_argument('--index',type=Path,default=ROOT/'output/web-demo/index.npz')
    args=parser.parse_args()
    manifest=package(args.output,args.model_dir,args.index)
    print(f"Packaged {len(manifest['files'])} files; sample {manifest['sample_version']}; {args.output.resolve()}")
