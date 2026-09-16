"""Verify hashes, isolated sample/search and persisted usage across two processes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('release',type=Path)
a=p.parse_args()
release=a.release.resolve()
manifest=json.loads((release/'manifest.json').read_text())
for name,expected in manifest['files'].items():
    path=release/name
    with path.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
    assert actual==expected['sha256'],f'Package file changed: {name}'
assert not list(release.rglob('*.sqlite')) and not list(release.rglob('auth.json'))
code='''
import json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from backend.app import demo_server as server
from fastapi.testclient import TestClient
root=Path(sys.argv[1])
assert Path(server.__file__).resolve().is_relative_to(root)
assert 'backend.app.main' not in sys.modules
assert len(server.sample['documents'])==10 and len(server.sample['graph']['issues'])==3
client=TestClient(server.app)
client.cookies.set(server.COOKIE,'a'*48)
status=client.get('/api/demo/status').json()
assert client.get('/').status_code==200
if sys.argv[2]=='first':
    assert status['remaining']==3
    from backend.app.demo_index import DemoIndex
    index=DemoIndex()
    evidence=index.search('윤해주는 온전한 녹색 황동 열쇠로 사물함을 열었다.',2)
    assert any('절단' in e['text'] for e in evidence)
    assert all(e['chapter_index']<=2 for e in evidence)
    with server.db() as c:
        c.execute('INSERT INTO calls VALUES(?,?,?,?,?,?,?,?)',('a'*48,'test-request-id','hash',server.today(),'test-ip','done',1,0))
    print(json.dumps({'sample_chapters':10,'relations':len(server.sample['graph']['relations']),'isolated_search':True,'static_root':True}))
else:
    assert status['remaining']==2
    print(json.dumps({'usage_survives_process_restart':True,'remaining':status['remaining']}))
'''
with tempfile.TemporaryDirectory(prefix='storyguard-portable-') as tmp:
    env={**os.environ,'STORY_GUARD_DATA_DIR':tmp+'/empty-desktop-data',
         'STORY_GUARD_DEMO_MODEL_DIR':str(release/'assets/models'),
         'STORY_GUARD_DEMO_INDEX':str(release/'assets/index.npz'),
         'STORY_GUARD_DEMO_USAGE_DB':tmp+'/persistent/usage.sqlite'}
    env.pop('STORY_GUARD_DEMO_OPENAI_API_KEY',None)
    for phase in ['first','restart']:
        r=subprocess.run([sys.executable,'-I','-c',code,str(release),phase],cwd=tmp,env=env,capture_output=True,text=True,check=True)
        print(r.stdout.strip())
print(f"Verified {len(manifest['files'])} hashes; no original desktop database or model path required.")
