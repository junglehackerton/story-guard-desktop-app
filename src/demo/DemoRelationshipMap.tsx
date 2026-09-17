import cytoscape, { type Core } from 'cytoscape';
import { CircleHelp, Monitor, Moon, Plus, RotateCcw, Sun, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { EntityNode, EvidenceChunk, GraphPayload, RelationEdge } from '../lib/types';
import { relatedRelations, type ReviewGraphFocus } from '../lib/reviewGraph';
import storyGuardMark from './assets/story-guard-mark.png';

type ThemeChoice = 'light' | 'dark' | 'system';
type MatchMode = 'all' | 'any';

type Props = {
  graph: GraphPayload;
  selectedEntityId: number | null;
  selectedRelationId: number | null;
  reviewFocus?: ReviewGraphFocus | null;
  reviewEvidence?: EvidenceChunk[];
  onSelectEntity: (entity: EntityNode | null) => void;
  onSelectRelation: (id: number | null) => void;
  onOpenEvidence: (documentId: number, quote?: string) => void;
  onReview: () => void;
  onIntro: () => void;
};

type Pair = { key: string; source: EntityNode; target: EntityNode; members: RelationEdge[] };

const themeStorageKey = 'storyguard-demo-theme-v1';
const typeLabels: Record<string, string> = {
  character: '인물', place: '장소', event: '사건', item: '아이템',
  organization: '조직', rule: '규칙', foreshadowing: '떡밥',
};
const visibleTypes = ['character', 'place', 'event', 'item'];

function initialTheme(): ThemeChoice {
  try {
    const saved = localStorage.getItem(themeStorageKey);
    if (saved === 'light' || saved === 'dark' || saved === 'system') return saved;
  } catch { /* Keep the system default when storage is unavailable. */ }
  return 'system';
}

function pairKey(a: number, b: number) {
  return [a, b].sort((x, y) => x - y).join(':');
}

function label(entity: EntityNode) {
  return entity.is_unresolved ? '미확인 대상' : entity.name;
}

function relationChapter(relation: RelationEdge) {
  const chapters = relation.claims?.flatMap(claim => claim.quotes.map(quote => quote.chapter_index)) ?? [];
  return chapters.length ? Math.min(...chapters) : null;
}

function excerpt(text: string, limit = 240) {
  const compact = text.replace(/\s+/g, ' ').trim();
  return compact.length > limit ? `${compact.slice(0, limit).trim()}…` : compact;
}

export function DemoRelationshipMap({
  graph, selectedEntityId, selectedRelationId, reviewFocus, reviewEvidence = [],
  onSelectEntity, onSelectRelation, onOpenEvidence, onReview, onIntro,
}: Props) {
  const [themeChoice, setThemeChoice] = useState<ThemeChoice>(initialTheme);
  const [systemDark, setSystemDark] = useState(() => typeof window !== 'undefined' && (window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false));
  const [activeTypes, setActiveTypes] = useState(() => new Set(['character']));
  const [showMoreTypes, setShowMoreTypes] = useState(false);
  const [matchMode, setMatchMode] = useState<MatchMode>('any');
  const [anchorIds, setAnchorIds] = useState<number[]>(() => selectedEntityId == null ? [] : [selectedEntityId]);
  const [chapterEnd, setChapterEnd] = useState<number | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);

  const theme = themeChoice === 'system' ? (systemDark ? 'dark' : 'light') : themeChoice;
  const entities = useMemo(() => graph.entities.filter(entity => !entity.name.startsWith('미확인 대상 #')), [graph.entities]);
  const entityById = useMemo(() => new Map(entities.map(entity => [entity.id, entity])), [entities]);
  const pairs = useMemo<Pair[]>(() => {
    const grouped = new Map<string, RelationEdge[]>();
    for (const relation of graph.relations) {
      if (!entityById.has(relation.source_entity_id) || !entityById.has(relation.target_entity_id)) continue;
      const key = pairKey(relation.source_entity_id, relation.target_entity_id);
      grouped.set(key, [...(grouped.get(key) ?? []), relation]);
    }
    return [...grouped.entries()].flatMap(([key, members]) => {
      const source = entityById.get(members[0].source_entity_id);
      const target = entityById.get(members[0].target_entity_id);
      return source && target ? [{ key, source, target, members }] : [];
    });
  }, [entityById, graph.relations]);
  const chapterValues = useMemo(() => graph.relations.flatMap(relation => relation.claims?.flatMap(claim => claim.quotes.map(quote => quote.chapter_index + 1)) ?? []), [graph.relations]);
  const maxChapter = Math.max(1, ...chapterValues);
  const effectiveChapterEnd = chapterEnd ?? maxChapter;

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!media) return;
    const update = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    try { localStorage.setItem(themeStorageKey, themeChoice); } catch { /* Theme remains available for this visit. */ }
  }, [themeChoice]);
  useEffect(() => {
    if (selectedEntityId != null) setAnchorIds(current => current.includes(selectedEntityId) ? current : [selectedEntityId, ...current].slice(0, 2));
  }, [selectedEntityId]);

  const reviewRelations = useMemo(() => {
    if (!reviewFocus) return [];
    const issue = graph.issues.find(item => item.id === reviewFocus.issueId);
    return relatedRelations(graph.relations, reviewFocus.chunkId == null ? issue?.evidence_chunk_ids ?? [] : [reviewFocus.chunkId]);
  }, [graph.issues, graph.relations, reviewFocus]);

  const filteredPairs = useMemo(() => pairs.filter(pair => {
    const typeMatches = activeTypes.has(pair.source.type) || activeTypes.has(pair.target.type);
    if (!typeMatches) return false;
    if (anchorIds.length) {
      const endpoints = new Set([pair.source.id, pair.target.id]);
      const anchorMatches = matchMode === 'all' ? anchorIds.every(id => endpoints.has(id)) : anchorIds.some(id => endpoints.has(id));
      if (!anchorMatches) return false;
    }
    return pair.members.some(member => {
      const chapter = relationChapter(member);
      return chapter == null || chapter + 1 <= effectiveChapterEnd;
    });
  }), [activeTypes, anchorIds, effectiveChapterEnd, matchMode, pairs]);

  const fallbackPairs = filteredPairs.length ? filteredPairs : pairs.filter(pair => activeTypes.has(pair.source.type) || activeTypes.has(pair.target.type));
  const canvasPairs = fallbackPairs.slice(0, 16);
  const canvasEntityIds = new Set(canvasPairs.flatMap(pair => [pair.source.id, pair.target.id]));
  const canvasEntities = entities.filter(entity => canvasEntityIds.has(entity.id)).slice(0, 18);
  const selectedRelation = graph.relations.find(relation => relation.id === selectedRelationId)
    ?? reviewRelations[0]
    ?? canvasPairs[0]?.members[0]
    ?? null;
  const selectedPair = selectedRelation ? pairs.find(pair => pair.members.some(member => member.id === selectedRelation.id)) ?? null : null;
  const selectedQuotes = selectedRelation?.claims?.flatMap(claim => claim.quotes) ?? [];
  const quoteByChunkId = new Map(graph.relations.flatMap(relation => relation.claims?.flatMap(claim => claim.quotes) ?? []).map(quote => [quote.chunk_id, quote]));
  const evidenceItems = reviewEvidence.length
    ? reviewEvidence.slice(0, 2).map((chunk, index) => { const quote = quoteByChunkId.get(chunk.id); return { key: `review-${chunk.id}`, chapter: quote?.chapter_index == null ? index + 1 : quote.chapter_index + 1, text: excerpt(quote?.quote || chunk.text), documentId: chunk.document_id }; })
    : selectedQuotes.slice(0, 2).map(quote => ({ key: `quote-${quote.chunk_id}`, chapter: quote.chapter_index + 1, text: excerpt(quote.quote), documentId: quote.document_id }));

  useEffect(() => {
    const container = canvasRef.current;
    if (!container) return;
    cyRef.current?.destroy();
    const shownIds = new Set(canvasEntities.map(entity => entity.id));
    const shownPairs = canvasPairs.filter(pair => shownIds.has(pair.source.id) && shownIds.has(pair.target.id));
    const width = Math.max(560, container.clientWidth);
    const height = Math.max(300, container.clientHeight);
    const columns = Math.max(3, Math.min(6, Math.ceil(Math.sqrt(canvasEntities.length * 1.6))));
    const positions = new Map<number, {x: number; y: number}>();
    canvasEntities.forEach((entity, index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);
      const rows = Math.ceil(canvasEntities.length / columns);
      const jitter = (index % 3 - 1) * 22;
      positions.set(entity.id, {
        x: 72 + column * ((width - 144) / Math.max(1, columns - 1)),
        y: 60 + row * ((height - 120) / Math.max(1, rows - 1)) + jitter,
      });
    });
    const cy = cytoscape({
      container,
      elements: [
        ...canvasEntities.map(entity => ({
          data: { id: String(entity.id), label: label(entity), type: entity.type },
          position: positions.get(entity.id),
          classes: anchorIds.includes(entity.id) ? 'anchor' : '',
        })),
        ...shownPairs.map(pair => ({
          data: { id: `r-${pair.key}`, relationId: pair.members[0].id, source: String(pair.source.id), target: String(pair.target.id) },
          classes: pair.members.some(member => member.id === selectedRelation?.id) ? 'selected' : '',
        })),
      ],
      layout: { name: 'preset', fit: false },
      minZoom: 0.55,
      maxZoom: 2,
      userPanningEnabled: true,
      userZoomingEnabled: true,
      style: [
        { selector: 'node', style: {
          'width': 13, 'height': 13, 'background-color': theme === 'dark' ? '#ebe2f7' : '#6f459a',
          'border-width': 2, 'border-color': theme === 'dark' ? '#2c2336' : '#faf8f3',
          'label': 'data(label)', 'font-size': 12, 'font-weight': 600,
          'color': theme === 'dark' ? '#eee9f2' : '#292631', 'text-valign': 'bottom', 'text-margin-y': 9,
          'text-background-color': theme === 'dark' ? '#211c26' : '#faf8f3', 'text-background-opacity': .82,
          'text-background-padding': '3px', 'text-wrap': 'ellipsis', 'text-max-width': '105px',
        } },
        { selector: "node[type='place']", style: { 'background-color': '#a96c3d' } },
        { selector: "node[type='event']", style: { 'background-color': '#a54f32' } },
        { selector: "node[type='item']", style: { 'background-color': '#66766b' } },
        { selector: 'node.anchor', style: { 'width': 20, 'height': 20, 'border-width': 4, 'border-color': theme === 'dark' ? '#d3baf0' : '#cdb5e7' } },
        { selector: 'edge', style: {
          'width': 1.5, 'line-color': theme === 'dark' ? '#655b6d' : '#b7aebb',
          'curve-style': 'bezier', 'target-arrow-shape': 'none', 'opacity': .8,
        } },
        { selector: 'edge.selected', style: { 'width': 3, 'line-color': theme === 'dark' ? '#d2b9ed' : '#7b4eb2', 'opacity': 1 } },
      ],
    });
    cy.on('tap', 'node', event => {
      const entity = entityById.get(Number(event.target.id())) ?? null;
      if (!entity) return;
      setAnchorIds(current => current.includes(entity.id) ? current : [entity.id, ...current].slice(0, 2));
      onSelectEntity(entity);
    });
    cy.on('tap', 'edge', event => onSelectRelation(Number(event.target.data('relationId'))));
    cyRef.current = cy;
    return () => { cy.destroy(); cyRef.current = null; };
  }, [anchorIds, canvasEntities, canvasPairs, entityById, onSelectEntity, onSelectRelation, selectedRelation?.id, theme]);

  function toggleType(type: string) {
    setActiveTypes(current => {
      const next = new Set(current);
      if (next.has(type) && next.size > 1) next.delete(type); else next.add(type);
      return next;
    });
  }
  function addAnchor() {
    const candidate = entities.find(entity => activeTypes.has(entity.type) && !anchorIds.includes(entity.id));
    if (!candidate) return;
    setAnchorIds(current => [...current, candidate.id].slice(-2));
    onSelectEntity(candidate);
  }
  function resetFilters() {
    setActiveTypes(new Set(['character']));
    setAnchorIds([]);
    setMatchMode('any');
    setChapterEnd(null);
    onSelectEntity(null);
    onSelectRelation(null);
  }

  const themeIcon = themeChoice === 'light' ? <Sun size={15}/> : themeChoice === 'dark' ? <Moon size={15}/> : <Monitor size={15}/>;
  return <main className="demo-map-shell" data-theme={theme}>
    <header className="demo-map-header">
      <button className="demo-map-brand" onClick={onIntro} aria-label="Story Guard 서비스 소개로 이동"><img className="story-guard-mark" src={storyGuardMark} alt="" aria-hidden="true"/><span>STORY GUARD</span><small>백로호텔의 마지막 손님</small></button>
      <nav aria-label="체험 화면"><button onClick={onReview}>설정 검토</button><button className="active" aria-current="page">관계 지도</button></nav>
      <div className="demo-map-header-actions">
        <label className="demo-theme-picker">{themeIcon}<span className="sr-only">화면 테마</span><select value={themeChoice} onChange={event => setThemeChoice(event.target.value as ThemeChoice)}><option value="light">라이트</option><option value="dark">다크</option><option value="system">시스템</option></select></label>
        <button className="demo-map-help" onClick={onIntro}><CircleHelp size={16}/> 사용 안내</button>
      </div>
    </header>

    <section className="demo-map-filters" aria-labelledby="demo-map-title">
      <div className="demo-map-title"><h1 id="demo-map-title">두 사람의 이야기가 겹치는 곳</h1><p>인물과 대상을 고르면, 함께 등장한 장면과 관계의 근거를 보여드려요.</p></div>
      <div className="demo-filter-row"><strong>대상 유형</strong><div className="demo-filter-chips">{(showMoreTypes ? Object.keys(typeLabels) : visibleTypes).map(type => <button key={type} className={activeTypes.has(type) ? 'active' : ''} aria-pressed={activeTypes.has(type)} onClick={() => toggleType(type)}>{typeLabels[type]}</button>)}<button className="subtle" aria-expanded={showMoreTypes} onClick={() => setShowMoreTypes(value => !value)}>{showMoreTypes ? '접기' : '더보기 ···'}</button></div></div>
      <div className="demo-filter-row"><strong>기준 대상</strong><div className="demo-filter-chips demo-anchor-chips">{anchorIds.map(id => { const entity = entityById.get(id); return entity ? <span key={id}>{label(entity)}<button aria-label={`${label(entity)} 선택 해제`} onClick={() => setAnchorIds(current => current.filter(item => item !== id))}><X size={13}/></button></span> : null; })}<button className="add" onClick={addAnchor}><Plus size={14}/> 대상 추가</button></div><div className="demo-match-toggle" role="group" aria-label="기준 대상 일치 방식"><button className={matchMode === 'all' ? 'active' : ''} onClick={() => setMatchMode('all')}>모두 일치</button><button className={matchMode === 'any' ? 'active' : ''} onClick={() => setMatchMode('any')}>하나라도</button></div></div>
      <div className="demo-filter-row demo-range-row"><strong>회차 범위</strong><div className="demo-range-control"><span>1화 — {effectiveChapterEnd}화</span><input aria-label="마지막 회차" type="range" min="1" max={maxChapter} value={effectiveChapterEnd} onChange={event => setChapterEnd(Number(event.target.value))}/></div><button className="demo-reset" onClick={resetFilters}><RotateCcw size={14}/> 초기화</button></div>
    </section>

    <section className="demo-map-graph" aria-labelledby="relationship-graph-title">
      <div className="demo-map-section-head"><div><h2 id="relationship-graph-title">관계 그래프</h2><p>{anchorIds.length ? `${anchorIds.map(id => label(entityById.get(id)!)).join(' · ')} 중심으로 찾은 연결` : '대상을 선택하면 연결이 좁혀집니다.'}</p></div><div className="demo-map-legend"><span><i className="character"/> 인물</span><span><i className="place"/> 장소</span><span><i className="event"/> 사건</span><span><i className="selected"/> 선택됨</span></div></div>
      {canvasEntities.length ? <div className="demo-map-canvas" ref={canvasRef} role="img" aria-label="인물과 대상의 관계 그래프"/> : <div className="demo-map-empty">선택한 조건에 맞는 관계가 없습니다. 필터를 초기화해 보세요.</div>}
      <p className="demo-map-hint">점을 선택하면 그 대상을 기준으로 연결을 다시 보여드려요. 선을 선택하면 아래에서 원문 근거를 확인할 수 있어요.</p>
    </section>

    <section className="demo-map-evidence" aria-labelledby="relationship-evidence-title">
      <div className="demo-map-section-head"><div><h2 id="relationship-evidence-title">함께 등장한 장면</h2><p>{selectedPair ? `${label(selectedPair.source)}와 ${label(selectedPair.target)}의 관계 근거` : '그래프에서 연결선을 선택해 보세요.'}</p></div>{reviewFocus && <button className="demo-review-return" onClick={onReview}>검토 화면으로 돌아가기</button>}</div>
      <div className="demo-evidence-grid">
        {evidenceItems.length ? evidenceItems.map(item => <article key={item.key}><span>{item.chapter}화</span><blockquote>{item.text.startsWith('“') ? item.text : `“${item.text}”`}</blockquote><button onClick={() => onOpenEvidence(item.documentId, item.text)}>원문에서 보기 ↗</button></article>) : <article className="demo-evidence-empty"><span>관계 설명</span><blockquote>“{selectedRelation?.claims?.[0]?.explanation || '선택한 연결에 저장된 원문 인용이 없습니다.'}”</blockquote></article>}
        <aside><span>이 장면에서 드러난 관계</span><strong>{selectedRelation?.display_label || selectedRelation?.type || '관계를 선택해 주세요'}</strong><p>{selectedRelation?.claims?.[0]?.explanation || '그래프의 선을 선택하면 관계를 뒷받침하는 장면과 설명이 이곳에 표시됩니다.'}</p><small>AI가 찾은 후보이며, 최종 판단은 작가가 직접 결정합니다.</small></aside>
      </div>
    </section>
  </main>;
}
