"""Fail-closed checks for synthetic prose skeleton repetition."""
from pathlib import Path
from collections import Counter
import re, sys
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path('output/validation/natural-novel-v3-20260915/episodes')
files=sorted(root.glob('episode-*.txt'))
patterns=[]
for p in files:
 t=p.read_text(encoding='utf-8')
 # Normalize variable noun spans to expose copied sentence skeletons.
 for s in re.split(r'(?<=[.!?。！？])\s+', t):
  s=re.sub(r'\s+',' ',s).strip()
  s=re.sub(r'도윤은 [^ ]+ [^ ]+에서 .{0,40}?발견하고 한참 말이 없었다','도윤은 장소에서 대상을 발견하고 한참 말이 없었다',s)
  s=re.sub(r'유나는 수첩[^.]*\.', '유나는 수첩에 기록했다.', s)
  if len(s)>18: patterns.append(s)
c=Counter(patterns)
repeats=[(k,v) for k,v in c.items() if v>=3]
print({'files':len(files),'repeated_skeletons':len(repeats),'examples':repeats[:5],'QUALITY_GATE':'PASS' if not repeats else 'FAIL'})
raise SystemExit(0 if not repeats else 1)
