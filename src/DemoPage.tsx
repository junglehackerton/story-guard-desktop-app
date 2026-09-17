import { useEffect, useRef, useState } from 'react';
import { WorkbenchNav, ManuscriptsPage, ReviewPage, PAGES, type Page, type SourceNavigation } from './components/Workbench';
import type { EntityNode, IssueStatus, ForeshadowingStatusValue } from './lib/types';
import type { ReviewGraphFocus } from './lib/reviewGraph';
import { sample, storageKey, loadJudgments, clueStorageKey, loadClueJudgments } from './demo/data';
import { DemoAnalysis, type LiveAnalysis } from './demo/DemoAnalysis';
import { DemoGuide } from './demo/DemoGuide';
import { guideAvailable, guideIssueId, evidenceChapters } from './demo/guide';
import './workbench.css';
import './demo.css';
import reviewPreview from './demo/assets/review-preview.jpg';
import graphPreview from './demo/assets/graph-preview.jpg';
import storyGuardMark from './demo/assets/story-guard-mark.png';
import { DemoRelationshipMap } from './demo/DemoRelationshipMap';
const noop = () => {};
const unchanged = async () => false;
const clueLabels = {unreviewed:'검토 전',in_progress:'진행 중',resolved:'회수 확인',intentional:'의도적 미회수'};
const tutorialStorageKey = 'storyguard-demo-tutorial-seen-v1';
const introStorageKey = 'storyguard-demo-intro-seen-v1';
function initialIntroOpen() {
  try { return localStorage.getItem(introStorageKey) !== 'yes'; } catch { return true; }
}
function initialTutorialOpen() {
  try { return localStorage.getItem(tutorialStorageKey) !== 'yes'; } catch { return true; }
}

function LiveAnalysisBanner({analysis,onGraph}:{analysis:LiveAnalysis;onGraph:()=>void}) {
  return <aside className="demo-live-handoff" role="status"><div><span className="badge">이번 방문자의 임시 분석</span><strong>{analysis.resolved?'수정안으로 해결 확인':analysis.verdict==='conflict'?'충돌 후보':analysis.verdict==='clear'?'뚜렷한 충돌 없음':'근거 부족'} · {analysis.resolved?'이전 후보가 해소됨':'임시 검토 상태'}</strong><p>{analysis.summary}</p></div><button onClick={onGraph}>영향받은 기존 관계 보기</button></aside>;
}

function DemoIntro({onEnter}:{onEnter:()=>void}) {
  const [revealed,setRevealed]=useState(false);
  const [previewMode,setPreviewMode]=useState<'review'|'graph'>('review');
  const [scrollProgress,setScrollProgress]=useState(0);
  useEffect(()=>{
    const timer=window.setInterval(()=>setPreviewMode(current=>current==='review'?'graph':'review'),5000);
    return ()=>window.clearInterval(timer);
  },[]);
  useEffect(()=>{
    const update=()=>{const max=document.documentElement.scrollHeight-window.innerHeight;setScrollProgress(max>0?Math.min(1,Math.max(0,window.scrollY/max)):0)};
    update(); window.addEventListener('scroll',update,{passive:true}); window.addEventListener('resize',update);
    return ()=>{window.removeEventListener('scroll',update);window.removeEventListener('resize',update)};
  },[]);
  useEffect(()=>{
    const nodes=[...document.querySelectorAll<HTMLElement>('.demo-intro-reveal')];
    if(!('IntersectionObserver' in window)){setRevealed(true);return;}
    const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting)entry.target.classList.add('is-visible')}),{threshold:.15});
    nodes.forEach(node=>observer.observe(node));
    return ()=>observer.disconnect();
  },[]);
  return <main className={`demo-intro-page ${revealed?'intro-ready':''}`}>
    <header className="demo-intro-nav"><a href="#intro-top" className="demo-intro-brand" aria-label="Story Guard 홈"><img className="story-guard-mark" src={storyGuardMark} alt="" aria-hidden="true" /><span>STORY GUARD</span></a><nav><a href="#intro-case">사례</a><a href="#intro-how">사용 방법</a><a href="#intro-download">다운로드</a><a href="#intro-principle">원칙</a><button onClick={onEnter}>핵심 기능 체험하기 <span>→</span></button></nav></header>
    <div className="demo-intro-progress" aria-hidden="true"><i style={{top:`${scrollProgress*72}%`}}></i></div>
    <section id="intro-top" className="demo-intro-hero demo-intro-reveal"><div className="demo-intro-copy"><span className="badge">작가를 위한 설정 연속성 작업실</span><h1>원고의 연결을<br/><em>지키는 작업실</em></h1><p>스토리 가드는 원문 근거와 함께 인물·물건·규칙의 연결을 확인합니다.</p><button className="primary demo-intro-cta" onClick={onEnter}>핵심 기능 체험하기 <span>→</span></button><small>로그인 없이 공개 샘플로 체험합니다.</small></div><div className="demo-intro-quote"><span>좋은 이야기는<br/>끝까지 이어지니까</span><i></i><small>STORY GUARD</small></div></section>
    <section id="intro-case" className="demo-intro-section demo-intro-case demo-intro-reveal"><div className="demo-intro-section-head"><span className="badge">CASE</span><h2>하나의 설정이,<br/>다른 이야기를 만들 수 있습니다.</h2><p>스토리 가드는 원고 속 근거를 바탕으로 이런 불일치를 찾아냅니다.</p></div><div className="demo-intro-case-grid"><article><strong>3화 · 열쇠를 잘라 버림</strong><p>“오래된 열쇠를 조용히 잘라 버렸다.”</p><small>사용할 수 없게 됨</small></article><div className="demo-intro-conflict" aria-label="설정 충돌">!</div><article><strong>5화 · 같은 열쇠가 다시 등장</strong><p>“주머니에서 익숙한 열쇠를 꺼내 문을 열었다.”</p><small>흠집 없이 다시 사용됨</small></article></div></section>
    <section className="demo-intro-section demo-intro-scope demo-intro-reveal"><div className="demo-intro-section-head"><span className="badge">WHAT IT FINDS</span><h2>문장 하나보다,<br/>이야기의 연결을 봅니다.</h2><p>서로 다른 회차에 흩어진 단서를 한 화면에서 확인합니다.</p></div><div className="demo-intro-scope-grid"><article><b>인물 관계</b><span>누가 누구에게 무엇을 했는지</span></article><article><b>물건의 상태</b><span>사라짐·교체·재등장의 흐름</span></article><article><b>시간과 규칙</b><span>시점·조건·예외의 충돌</span></article><article><b>떡밥 후보</b><span>아직 회수되지 않은 단서</span></article></div></section>
    <section id="intro-how" className="demo-intro-section demo-intro-how demo-intro-reveal"><div className="demo-intro-section-head"><span className="badge">HOW IT WORKS</span><h2>세 단계로 확인합니다.</h2><p>복잡한 설정을 한눈에 파악할 수 있도록 필요한 정보만 보여줍니다.</p></div><ol><li><b>01</b><h3>찾기</h3><p>관련 설정과 사건을 원문에서 찾습니다.</p></li><li><b>02</b><h3>비교하기</h3><p>등장 위치와 상태를 근거로 비교합니다.</p></li><li><b>03</b><h3>판단하기</h3><p>작가가 직접 다음 결정을 선택합니다.</p></li></ol></section>
    <section className="demo-intro-section demo-intro-preview demo-intro-reveal"><div className="demo-intro-section-head"><span className="badge">IN THE WORKSPACE</span><h2>원문, 검토, 관계를<br/>한 흐름으로 봅니다.</h2><p>실제 작업실 화면을 공개 샘플로 먼저 확인할 수 있습니다.</p></div><div className="demo-intro-preview-tabs" role="tablist" aria-label="작업실 미리보기"><button role="tab" aria-selected={previewMode==='review'} onClick={()=>setPreviewMode('review')}>검토 결과</button><button role="tab" aria-selected={previewMode==='graph'} onClick={()=>setPreviewMode('graph')}>관계 지도</button></div><figure className="demo-intro-preview-frame"><img key={previewMode} className="demo-intro-preview-image" src={previewMode==='review'?reviewPreview:graphPreview} alt={previewMode==='review'?'원문 근거가 표시된 검토 결과 화면':'인물과 물건의 연결을 보여주는 관계 지도 화면'} /><figcaption>{previewMode==='review'?'원문 근거를 읽고 작가가 판단하는 화면':'인물·물건·사건의 연결을 따라가는 화면'}</figcaption></figure></section>
    <section id="intro-download" className="demo-intro-section demo-intro-download demo-intro-reveal"><div className="demo-intro-section-head"><span className="badge">DESKTOP APP</span><h2>체험이 끝나면,<br/>작업실을 설치하세요.</h2><p>웹 체험은 공개 샘플로 제공됩니다. 실제 원고를 보관하고 계속 분석하려면 운영체제에 맞는 설치형 프로그램을 사용하세요.</p></div><div className="demo-intro-download-grid"><article><div><strong>macOS</strong><span>Apple Silicon · DMG</span></div><a className="primary" href="https://github.com/wanted-storyguard/StoryGaurd/releases" target="_blank" rel="noreferrer">Mac 다운로드 <span>↗</span></a><small>최신 버전은 GitHub Releases에서 확인합니다.</small></article><article><div><strong>Windows</strong><span>Windows · 설치 파일</span></div><a href="https://github.com/wanted-storyguard/StoryGaurd/releases" target="_blank" rel="noreferrer">Windows 다운로드 <span>↗</span></a><small>Windows 빌드가 공개되면 같은 릴리스 페이지에서 받을 수 있습니다.</small></article></div></section>
    <section id="intro-principle" className="demo-intro-principle demo-intro-reveal"><div><span className="badge">OUR PRINCIPLE</span><h2>AI는 결론을 대신 내리지 않습니다.</h2><p>가능성을 비추고 근거를 제시합니다. 이야기의 방향을 정하는 사람은 언제나 작가입니다.</p></div><button onClick={onEnter} className="primary">핵심 기능 체험하기 <span>→</span></button></section>
    <footer className="demo-intro-footer">STORY GUARD <span>원문 근거와 함께, 더 오래 이어지는 이야기</span></footer>
  </main>;
}

export default function DemoPage() {
  const [page, setPage] = useState<Page>('review');
  const [guided, setGuided] = useState(guideAvailable);
  const [judgments, setJudgments] = useState(loadJudgments);
  const [clues, setClues] = useState(loadClueJudgments);
  const [source, setSource] = useState<SourceNavigation>();
  const [sourceReturn, setSourceReturn] = useState<Page>('review');
  const [entity, setEntity] = useState<EntityNode | null>(null);
  const [relation, setRelation] = useState<number | null>(null);
  const [focus, setFocus] = useState<ReviewGraphFocus | null>(null);
  const [notice, setNotice] = useState('');
  const [tutorialOpen, setTutorialOpen] = useState(initialTutorialOpen);
  const [introOpen, setIntroOpen] = useState(initialIntroOpen);
  const [liveAnalysis, setLiveAnalysis] = useState<LiveAnalysis | null>(null);
  const [completionOpen, setCompletionOpen] = useState(false);
  const workspace = useRef<HTMLElement>(null);
  const graph = {...sample.graph, issues: [...sample.graph.issues].sort((a,b)=>Number(b.id===guideIssueId)-Number(a.id===guideIssueId)).map(i => ({...i, status: judgments[i.id] ?? i.status}))};
  const evidence = Object.fromEntries(graph.issues.map(i => [i.id, sample.chunks.filter(c => i.evidence_chunk_ids.includes(c.id))]));
  const liveEvidence = liveAnalysis?.evidence.map(item => sample.chunks.find(chunk => chunk.id === item.id) ?? ({id:item.id, document_id:item.document_id, project_id:sample.project.id, chunk_index:0, text:item.text, start_offset:0, end_offset:item.text.length} as typeof sample.chunks[number])) ?? [];
  const liveTarget = (liveAnalysis && graph.entities.find(entity => liveAnalysis.text.includes(entity.name)))
    || (liveAnalysis ? graph.entities.find(entity => entity.name.includes('황동 열쇠')) : null)
    || (liveAnalysis ? graph.entities.find(entity => liveEvidence.some(item => item.text.includes(entity.name))) : null) || null;
  const liveGraph = liveAnalysis?.resolved ? {...graph, issues: graph.issues.map(issue => issue.id===guideIssueId ? {...issue, status:'accepted' as const, description:liveAnalysis.summary} : issue)} : liveAnalysis && liveAnalysis.verdict !== 'clear' ? {...graph, issues: [...graph.issues, {id:-1, project_id:sample.project.id, severity:liveAnalysis.verdict==='conflict'?'high' as const:'medium' as const, category:'contradiction' as const, title:'새 문장 검토 · '+(liveAnalysis.verdict==='conflict'?'충돌 후보':'근거 부족'), description:liveAnalysis.summary, evidence_chunk_ids:liveEvidence.map(item=>item.id), status:'open' as const}]} : graph;
  const liveEvidenceMap = liveAnalysis ? {...evidence, [-1]: liveEvidence} : evidence;
  useEffect(() => { workspace.current?.scrollTo(0,0); workspace.current?.closest('.app-shell')?.scrollTo(0,0); }, [page,guided]);
  function navigate(next: Page) {
    if(next==='welcome') { startGuide(); return; }
    if(next==='review')setGuided(false);
    setPage(['welcome','settings','setup','projects'].includes(next) ? 'analysis' : next);
  }
  function startGuide() { setLiveAnalysis(null); setGuided(guideAvailable()); setPage('review'); }
  function beginTutorial() {
    try { localStorage.setItem(tutorialStorageKey, 'yes'); } catch { /* session-only is fine */ }
    setTutorialOpen(false); startGuide();
  }
  function enterDemo() {
    try { localStorage.setItem(introStorageKey, 'yes'); } catch { /* session-only is fine */ }
    setIntroOpen(false); setTutorialOpen(false); startGuide();
  }
  function allReviews() { setGuided(false); setPage('review'); }
  function openSource(documentId: number, quote?: string) { setSourceReturn(page); setSource({documentId, quote}); setPage('manuscripts'); }
  async function save(id: number, status: IssueStatus) {
    const previous = judgments[id] ?? 'open';
    const next = {...judgments, [id]: status}; setJudgments(next);
    try { localStorage.setItem(storageKey, JSON.stringify(next)); }
    catch { setNotice('브라우저 저장이 차단되어 판단은 이 화면을 닫기 전까지만 유지됩니다.'); }
    if (id === guideIssueId && previous === 'open' && status !== 'open') {
      try {
        if (sessionStorage.getItem('storyguard-demo-completion-seen-v1') !== 'yes') {
          sessionStorage.setItem('storyguard-demo-completion-seen-v1', 'yes');
          setCompletionOpen(true);
        }
      } catch { setCompletionOpen(true); }
    }
    return true;
  }
  function saveClue(id: number, status: ForeshadowingStatusValue) {
    const next = {...clues,[id]:status}; setClues(next);
    try { localStorage.setItem(clueStorageKey,JSON.stringify(next)); }
    catch { setNotice('브라우저 저장이 차단되어 판단은 이 화면을 닫기 전까지만 유지됩니다.'); }
  }
  function reset() {
    try { localStorage.removeItem(storageKey); localStorage.removeItem(clueStorageKey); setJudgments({}); setClues({}); startGuide(); setNotice('작가 판단과 떡밥 상태를 초기화했습니다. AI 이용 횟수는 유지됩니다.'); }
    catch { setNotice('브라우저 저장소를 사용할 수 없어 초기화하지 못했습니다.'); }
  }
  if (introOpen) return <DemoIntro onEnter={enterDemo}/>;
  if (page==='graph') return <DemoRelationshipMap
    graph={liveGraph}
    selectedEntityId={entity?.id ?? null}
    selectedRelationId={relation}
    reviewFocus={focus}
    reviewEvidence={focus ? liveEvidenceMap[focus.issueId] : []}
    onSelectEntity={setEntity}
    onSelectRelation={setRelation}
    onOpenEvidence={openSource}
    onReview={()=>setPage('review')}
    onIntro={()=>setIntroOpen(true)}
  />;
  return <div className={`app-shell workbench demo-workbench page-${page}`}>
    <WorkbenchNav demo page={page} onPage={navigate} project={sample.project} projects={[sample.project]} onProject={startGuide} onReset={reset}/>
    <main className="workspace" ref={workspace}>
      <header className="workspace-header"><div className="title-area"><h1 className="page-title">{guided && page==='review' ? '원문으로 확인하고, 작가가 판단하세요' : PAGES[page][0]}</h1><p className="page-description">{guided && page==='review' ? '긴 소설에서 앞뒤가 달라진 설정을 근거와 함께 찾습니다.' : PAGES[page][1]}</p><div className="project-title-row"><h2>{sample.project.title}</h2></div></div><div className="status-strip"><span className="badge">웹 체험판</span><strong>공개 샘플 10화</strong><button className="demo-intro-back" onClick={()=>setIntroOpen(true)}>서비스 소개</button></div></header>
      {!(guided && page==='review') && <aside className="demo-notice"><div><strong>{page==='analysis' ? '직접 입력하는 실시간 AI 분석' : '저장된 실제 분석 결과를 탐색 중입니다.'}</strong><p>{page==='analysis' ? 'AI 연결 없이도 샘플의 근거 비교와 작가 판단을 체험할 수 있습니다.' : '샘플 원고는 읽기 전용입니다. 판단은 이 브라우저에 저장되며 다른 방문자에게 영향을 주지 않습니다.'}</p></div><button onClick={startGuide}>첫 사례로 돌아가기</button></aside>}
      {notice && <p className="demo-storage-notice" role="status">{notice}</p>}
      <section className="page-content" hidden={page!=='analysis'}><DemoAnalysis active={page==='analysis'} onSource={openSource} onResult={setLiveAnalysis} onGraph={()=>{setEntity(liveTarget);setRelation(null);setFocus(null);setPage('graph');}} onReview={allReviews}/></section>
      <section className="page-content" hidden={page!=='manuscripts'}>
        {source && <button className="demo-source-return" onClick={()=>setPage(sourceReturn)}>← {sourceReturn==='review' && guided ? '열쇠 사례의 근거 비교로' : '이전 화면으로'} 돌아가기</button>}
        <ManuscriptsPage readOnly active={page==='manuscripts'} documents={sample.documents} settings={[]} sourceRequest={source} loading={false} onImport={noop} onDelete={noop} onReplace={noop} onEdit={unchanged} onAnalyze={()=>setPage('analysis')} onCreateSetting={unchanged} onUpdateSetting={unchanged} onDeleteSetting={noop}/>
      </section>
      {page==='review' && <section className="page-content">{liveAnalysis && <LiveAnalysisBanner analysis={liveAnalysis} onGraph={()=>{setEntity(liveTarget);setRelation(null);setFocus(null);setPage('graph');}}/>}{guided ? <DemoGuide status={judgments[guideIssueId] ?? 'open'} onSave={save} onSource={openSource} onGraph={()=>{setEntity(sample.graph.entities.find(e=>e.name==='녹색 플라스틱 머리가 달린 황동 열쇠') ?? null);setRelation(null);setFocus({issueId:guideIssueId});setPage('graph');}} onReview={allReviews} onClues={()=>setPage('foreshadowing')} onAnalyze={()=>setPage('analysis')} onTutorial={()=>setTutorialOpen(true)}/> : <ReviewPage graph={liveGraph} evidence={liveEvidenceMap} documents={sample.documents} history={[]} onStatus={save} onGraph={f=>{setFocus(f);setPage('graph');}} onOpenDocument={openSource} onAnalysis={()=>setPage('analysis')}/>}</section>}
      {page==='foreshadowing' && <section className="page-content"><div className="surface"><h2>추출된 떡밥 후보</h2><p className="muted">AI가 찾은 단서 후보입니다. 언급이 없다는 이유만으로 미회수라고 단정하지 않고, 작가가 상태를 결정합니다. 회차는 저장된 언급·연결 근거가 있는 범위입니다.</p>{graph.entities.filter(e=>e.type==='foreshadowing').map(e=>{
        const current = clues[e.id] ?? 'unreviewed'; const chapters = evidenceChapters(e.id);
        return <article className="source-card foreshadowing-card" key={e.id}><div><h3>{e.name}</h3><span className={`setting-certainty ${current}`}>{clueLabels[current]}</span></div><p>{e.summary}</p><div className="demo-chapter-links"><span>근거 회차</span>{chapters.length ? chapters.map(d=><button className="text-action" key={d.id} onClick={()=>openSource(d.id)}>{d.chapter_index+1}화 원문</button>) : <span>저장된 회차 근거 없음 · 등장 시점 확인 필요</span>}</div><div className="foreshadowing-actions"><label>작가 판단<select aria-label={`${e.name} 상태`} value={current} onChange={event=>saveClue(e.id,event.target.value as ForeshadowingStatusValue)}>{Object.entries(clueLabels).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><button onClick={()=>{setEntity(e);setRelation(null);setFocus(null);setPage('graph');}}>관계 지도에서 확인</button></div></article>;
      })}</div></section>}
      <footer className="demo-footer">데스크톱 앱은 원고를 기기에 보관합니다. 웹 체험은 공개 샘플을 사용하며, 직접 입력한 새 문장 검토는 서버와 외부 AI에서 처리합니다.</footer>
    </main>
    {tutorialOpen && <div className="demo-tutorial-backdrop" role="presentation"><section className="demo-tutorial" role="dialog" aria-modal="true" aria-labelledby="demo-tutorial-title">
      <span className="badge">STORY GUARD · 3분 체험</span>
      <h2 id="demo-tutorial-title">작가가 원고를 점검하는 순간을<br/>직접 체험해 보세요</h2>
      <p className="demo-tutorial-lead">처음부터 모든 기능을 배울 필요는 없습니다. 이미 분석된 한 장면을 따라가며 스토리 가드가 무엇을 찾아주는지 확인합니다.</p>
      <div className="demo-tutorial-scenario"><strong>당신의 상황</strong><p>다음 화를 공개하기 전, 앞에서 없앴던 물건이 뒤에서 다시 등장하지 않는지 점검하려고 합니다.</p></div>
      <ol className="demo-tutorial-steps"><li><b>근거 비교</b><span>3화와 5화의 열쇠 장면을 읽습니다.</span></li><li><b>작가 판단</b><span>오류인지 보류할지 직접 결정합니다.</span></li><li><b>맥락 탐색</b><span>관계와 단서로 더 깊이 들어갑니다.</span></li></ol>
      <p className="demo-tutorial-note">샘플 원고는 읽기 전용이며, 판단은 이 브라우저에만 저장됩니다.</p>
      <div className="demo-tutorial-actions"><button onClick={beginTutorial} className="primary">열쇠 사례 시작하기</button><button onClick={beginTutorial}>설명 없이 둘러보기</button></div>
    </section></div>}
    {completionOpen && <div className="demo-completion-backdrop" role="presentation"><section className="demo-completion-modal" role="dialog" aria-modal="true" aria-labelledby="demo-completion-title"><span className="badge">체험 1단계 완료</span><h2 id="demo-completion-title">AI가 찾은 근거를 확인했습니다.</h2><p>이제 관계 지도와 검토 결과에서 판단이 어떻게 반영되는지 이어서 확인해 보세요.</p><div className="demo-completion-modal-note"><strong>웹 체험판 안내</strong><span>전체 원고를 기기에 보관하고 계속 분석하려면 최종 설치형 프로그램을 사용합니다.</span></div><div className="demo-completion-actions"><button className="primary" onClick={()=>setCompletionOpen(false)}>결과 계속 보기</button><a href="https://github.com/wanted-storyguard/StoryGaurd/releases" target="_blank" rel="noreferrer">프로그램 다운로드 안내</a></div></section></div>}
  </div>;
}
