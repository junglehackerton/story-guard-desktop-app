import { relatedRelations, relationJudgments, judgmentLabel, type ReviewGraphFocus } from "../lib/reviewGraph";
import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core } from "cytoscape";
import type { EntityNode, GraphPayload, RelationEdge, EvidenceChunk } from "../lib/types";
import haejuPortrait from "../demo/assets/evidence-board/haeju.jpg";
import mingyubaekPortrait from "../demo/assets/evidence-board/mingyubaek.jpg";
import baekroHotel from "../demo/assets/evidence-board/baekro-hotel.jpg";
import guestLedger from "../demo/assets/evidence-board/guest-ledger.jpg";
import generatedMalePortrait from "../demo/assets/evidence-board/generated/character-male.jpg";
import generatedBrassKey from "../demo/assets/evidence-board/generated/brass-key-generated.jpg";
import generatedCoastalHotel from "../demo/assets/evidence-board/generated/coastal-hotel.jpg";
import generatedOmalsoon from "../demo/assets/evidence-board/generated/ohmalsun.jpg";
import generatedSeowoo from "../demo/assets/evidence-board/generated/seowoo-generated.jpg";
import generatedTechnician from "../demo/assets/evidence-board/generated/technician.jpg";
import generatedMinseoryeong from "../demo/assets/evidence-board/generated/minseoryeong-generated.jpg";
import generatedKangtaeoh from "../demo/assets/evidence-board/generated/kangtaeoh.jpg";
import generatedJindogyeom from "../demo/assets/evidence-board/generated/jindogyeom.jpg";

type Props = {
  projectId: number | null;
  reviewFocus?: ReviewGraphFocus | null;
  compactReview?: boolean;
  reviewEvidence?: EvidenceChunk[];
  onCloseReview?: () => void;
  onBackReview?: () => void;
  graph: GraphPayload;
  visible?: boolean;
  selectedEntityId: number | null;
  selectedRelationId?: number | null;
  onSelectEntity: (entity: EntityNode | null) => void;
  onSelectRelation?: (id: number | null) => void;
  onReviewRelation?: (id: number) => void;
  onOpenEvidence?: (documentId: number, quote: string) => void;
};

type Pair = { key: string; source: EntityNode; target: EntityNode; members: RelationEdge[] };
const typeLabel: Record<string, string> = { character: "인물", place: "장소", organization: "조직", item: "아이템", event: "사건", rule: "규칙", foreshadowing: "떡밥" };
const typeColor: Record<string, string> = { character: "#24635B", place: "#4F817D", organization: "#8A5A20", item: "#B78343", event: "#7B6B4B", rule: "#39796E", foreshadowing: "#6687BD" };
const entityAssets = [
  { names: ["해주", "윤해주"], src: haejuPortrait },
  { names: ["민규백"], src: mingyubaekPortrait },
  { names: ["민서령"], src: generatedMinseoryeong },
  { names: ["서우"], src: generatedSeowoo },
  { names: ["호텔", "백로호텔"], src: baekroHotel },
  { names: ["백로도", "항구", "개인 선착장", "경매장", "서관 숙소"], src: generatedCoastalHotel },
  { names: ["장부", "수첩", "명부"], src: guestLedger },
  { names: ["열쇠", "녹색 플라스틱 머리가 달린 황동 열쇠"], src: generatedBrassKey },
  { names: ["금고", "지하 문서금고", "금고 부품", "장부 원본"], src: guestLedger },
  { names: ["백로라는 이름의 파일", "기록 테이프", "사진", "편지", "문 밖에 끼운 보강봉"], src: guestLedger },
  { names: ["오말순"], src: generatedOmalsoon },
  { names: ["기술자"], src: generatedTechnician },
  { names: ["강태오"], src: generatedKangtaeoh },
  { names: ["진도겸"], src: generatedJindogyeom },
  { names: ["윤재문"], src: generatedMalePortrait },
];
function assetForEntity(entity: EntityNode | null | undefined) {
  if (!entity) return null;
  return entityAssets.find(asset => asset.names.some(name => entity.name === name || entity.name.includes(name)))?.src ?? null;
}

function entityLabel(entity: EntityNode) { return entity.is_unresolved ? "미확인 대상" : entity.name; }
function pairKey(a: number, b: number) { return [a, b].sort((x, y) => x - y).join(":"); }
function isIssue(relation: RelationEdge) {
  // A generic relation label is not itself an error. Mark a link for review
  // only when it is explicitly weak or has no usable evidence at all. GPT
  // claims can carry quotes even when the normalized evidence id list is
  // empty, so those claims must count as support.
  const hasQuotedClaim = relation.claims?.some(claim => (claim.quotes?.length ?? 0) > 0) ?? false;
  return Boolean(relation.has_unresolved_endpoint) || relation.is_weak || (!relation.evidence_chunk_ids.length && !hasQuotedClaim);
}

/** A writer-first relationship explorer. The canvas is a compact index; the
 * relation cards below remain exhaustive and carry the evidence interaction. */
export function RelationshipExplorer({ graph, selectedEntityId, selectedRelationId, onSelectEntity, onSelectRelation, onReviewRelation, onOpenEvidence, reviewFocus, reviewEvidence = [], onCloseReview, onBackReview, compactReview = false }: Props) {
  // Keep the review handoff visible even if a background refresh briefly
  // replaces the issue list while the graph page is mounting. The evidence
  // payload is already enough to explain what was selected.
  const reviewIssue = (graph.issues ?? []).find(issue => issue.id === reviewFocus?.issueId)
    ?? (reviewFocus ? { id: reviewFocus.issueId, title: "검토 후보", description: "선택한 검토 후보의 관계와 원문 근거입니다.", status: "open" as const, evidence_chunk_ids: reviewEvidence.map(chunk => chunk.id) } : undefined);
  const reviewRelations = relatedRelations(graph.relations, reviewFocus?.chunkId == null ? reviewIssue?.evidence_chunk_ids ?? [] : [reviewFocus.chunkId]);
  const reviewIds = new Set(reviewRelations.map(relation => relation.id));
  const needsReview = (relation: RelationEdge) => isIssue(relation) || relationJudgments(relation, graph.issues ?? []).some(issue => issue.status !== 'ignored');
  const [mode, setMode] = useState<"focus" | "issues" | "timeline" | "all">("focus");
  const [query, setQuery] = useState("");
  const [hoveredPairKey, setHoveredPairKey] = useState<string | null>(null);
  const [timelineChapter, setTimelineChapter] = useState<number | null>(null);
  const [showAllRelations, setShowAllRelations] = useState(false);
  const [canvasSize, setCanvasSize] = useState({ width: 800, height: 470 });
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const entities = useMemo(() => graph.entities.filter(entity => entity.is_unresolved || !entity.name.startsWith("미확인 대상 #")), [graph.entities]);
  const entityById = useMemo(() => new Map(entities.map(entity => [entity.id, entity])), [entities]);
  const entityGroups = useMemo(() => {
    const groups = new Map<string, EntityNode[]>();
    for (const entity of entities) groups.set(entity.type, [...(groups.get(entity.type) ?? []), entity]);
    return [...groups.entries()]
      .sort(([a], [b]) => (typeLabel[a] ?? a).localeCompare(typeLabel[b] ?? b, "ko"))
      .map(([type, items]) => [type, [...items].sort((a, b) => a.name.localeCompare(b.name, "ko"))] as const);
  }, [entities]);
  const pairs = useMemo<Pair[]>(() => {
    const grouped = new Map<string, RelationEdge[]>();
    for (const relation of graph.relations) {
      if (!entityById.has(relation.source_entity_id) || !entityById.has(relation.target_entity_id) || relation.source_entity_id === relation.target_entity_id) continue;
      const key = pairKey(relation.source_entity_id, relation.target_entity_id);
      grouped.set(key, [...(grouped.get(key) ?? []), relation]);
    }
    return [...grouped.entries()].flatMap(([key, members]) => {
      const source = entityById.get(members[0].source_entity_id); const target = entityById.get(members[0].target_entity_id);
      return source && target ? [{ key, source, target, members }] : [];
    });
  }, [graph.relations, entityById]);
  const focus = selectedEntityId == null ? null : entityById.get(selectedEntityId) ?? null;
  const selectedRelation = selectedRelationId == null ? null : graph.relations.find(relation => relation.id === selectedRelationId) ?? null;
  const selectedPair = selectedRelation ? pairs.find(pair => pair.members.some(member => member.id === selectedRelation.id)) ?? null : null;
  const focusPairs = useMemo(() => {
    if (reviewIssue) return pairs.filter(pair => pair.members.some(member => reviewIds.has(member.id)));
    if (!focus) return pairs;
    return pairs.filter(pair => pair.source.id === focus.id || pair.target.id === focus.id);
  }, [pairs, focus, reviewIssue, reviewFocus?.chunkId]);
  const pairChapters = useMemo(() => {
    const result = new Map<string, number[]>();
    for (const pair of pairs) {
      const chapters = pair.members.flatMap(member => (member.claims ?? []).flatMap(claim => (claim.quotes ?? []).map(quote => quote.chapter_index)));
      result.set(pair.key, [...new Set(chapters)].sort((a, b) => a - b));
    }
    return result;
  }, [pairs]);
  const timelineChapters = useMemo(() => [...new Set([...pairChapters.values()].flat())].sort((a, b) => a - b), [pairChapters]);
  const visiblePairs = useMemo(() => {
    let next = mode === "issues" ? focusPairs.filter(pair => pair.members.some(needsReview)) : focusPairs;
    if (mode === "timeline" && timelineChapter !== null) {
      next = next.filter(pair => (pairChapters.get(pair.key) ?? []).some(chapter => chapter <= timelineChapter));
    }
    if (query.trim()) next = next.filter(pair => `${entityLabel(pair.source)} ${entityLabel(pair.target)} ${pair.members.map(member => member.display_label || member.type).join(" ")}`.toLowerCase().includes(query.trim().toLowerCase()));
    return next.sort((a, b) => Number(b.members.some(member => member.id === selectedRelationId)) - Number(a.members.some(member => member.id === selectedRelationId)) || b.members.length - a.members.length || a.key.localeCompare(b.key));
  }, [focusPairs, mode, query, pairChapters, timelineChapter, graph.issues, selectedRelationId]);
  // Keep the evidence index readable even in focus/issues modes. The canvas
  // is deliberately compact, so the card list should expose the same small
  // first page and let the writer opt into the exhaustive list.
  const renderedPairs = showAllRelations ? visiblePairs : visiblePairs.slice(0, 12);
  useEffect(() => {
    setShowAllRelations(false);
    // A relation selected in one filter can disappear from the next result
    // set. Clear the inspector so it never explains a stale, invisible card.
    if (!reviewIssue && selectedRelation && !visiblePairs.some(pair => pair.members.some(member => member.id === selectedRelation.id))) onSelectRelation?.(null);
  }, [mode, query, selectedEntityId, timelineChapter, visiblePairs, selectedRelationId]);
  useEffect(() => { if (reviewIssue) { setMode("focus"); setQuery(""); setTimelineChapter(null); } }, [reviewFocus]);
  const canvasEntities = useMemo(() => {
    if (focus) {
      // Keep the timeline canvas bounded. The relation cards remain exhaustive;
      // the canvas is an orientation aid and should not become a hairball.
      const basePairs = mode === "timeline" ? focusPairs.slice(0, 10) : focusPairs;
      const ids = new Set(basePairs.flatMap(pair => [pair.source.id, pair.target.id]));
      return entities.filter(entity => ids.has(entity.id));
    }
    // In timeline mode derive the canvas roster from the complete filtered
    // corpus, not the current slider value. This keeps a node's identity and
    // position stable while the author scrubs through chapters.
    const basePairs = mode === "timeline" ? (query.trim() ? visiblePairs : focusPairs).slice(0, 10) : visiblePairs.slice(0, 10);
    const ids = new Set(basePairs.flatMap(pair => [pair.source.id, pair.target.id]));
    return entities.filter(entity => ids.has(entity.id)).slice(0, 14);
  }, [entities, focus, focusPairs, mode, query, visiblePairs]);
  useEffect(() => {
    const element = canvasRef.current;
    if (!element) return;
    const update = () => setCanvasSize({ width: Math.max(320, element.clientWidth), height: Math.max(260, element.clientHeight) });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const positions = useMemo(() => {
    const result = new Map<number, { x: number; y: number }>();
    const center = focus ?? canvasEntities[0];
    if (!center) return result;
    if (mode === "timeline") {
      const ordered = [...canvasEntities].sort((a, b) => {
        const aChapter = Math.min(...pairs.filter(pair => pair.source.id === a.id || pair.target.id === a.id).flatMap(pair => pair.members.flatMap(member => member.claims?.flatMap(claim => claim.quotes.map(quote => quote.chapter_index)) ?? [])), Infinity);
        const bChapter = Math.min(...pairs.filter(pair => pair.source.id === b.id || pair.target.id === b.id).flatMap(pair => pair.members.flatMap(member => member.claims?.flatMap(claim => claim.quotes.map(quote => quote.chapter_index)) ?? [])), Infinity);
        return aChapter - bChapter || a.name.localeCompare(b.name);
      });
      const columns = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(ordered.length))));
      const padding = 56;
      const columnGap = columns === 1 ? 0 : Math.max(90, (canvasSize.width - padding * 2) / (columns - 1));
      const rows = Math.ceil(ordered.length / columns);
      const rowGap = rows === 1 ? 0 : Math.max(76, (canvasSize.height - padding * 2) / (rows - 1));
      ordered.forEach((entity, index) => result.set(entity.id, { x: columns === 1 ? canvasSize.width / 2 : padding + (index % columns) * columnGap, y: rows === 1 ? canvasSize.height / 2 : padding + Math.floor(index / columns) * rowGap }));
      return result;
    }
    const centerX = canvasSize.width / 2; const centerY = canvasSize.height / 2;
    result.set(center.id, { x: centerX, y: centerY });
    const others = canvasEntities.filter(entity => entity.id !== center.id);
    const radiusX = Math.max(90, Math.min(canvasSize.width / 2 - 54, 120 + others.length * 14));
    const radiusY = Math.max(70, Math.min(canvasSize.height / 2 - 48, 76 + others.length * 6));
    if (others.length === 1) {
      result.set(others[0].id, { x: centerX + radiusX, y: centerY });
      return result;
    }
    if (others.length === 2) {
      others.forEach((entity, index) => result.set(entity.id, { x: centerX + (index === 0 ? -radiusX : radiusX), y: centerY }));
      return result;
    }
    others.forEach((entity, index) => { const angle = -Math.PI / 2 + (index / Math.max(1, others.length)) * Math.PI * 2; result.set(entity.id, { x: centerX + Math.cos(angle) * radiusX, y: centerY + Math.sin(angle) * radiusY }); });
    return result;
  }, [canvasEntities, canvasSize, focus, mode, pairs]);
  const issueCount = pairs.filter(pair => pair.members.some(needsReview)).length;
  const confirmedCount = pairs.length - issueCount;
  const canvasPairs = focus ? focusPairs : pairs;
  const canvasIssueCount = canvasPairs.filter(pair => pair.members.some(needsReview)).length;
  const canvasConfirmedCount = canvasPairs.length - canvasIssueCount;
  const selectEntity = (entity: EntityNode | null) => { onSelectRelation?.(null); onSelectEntity(entity); };
  useEffect(() => {
    if (!canvasRef.current) return;
    cyRef.current?.destroy();
    // Keep the Cytoscape roster identical to the roster used for position
    // calculation. Previously the preview positioned the first 10 pairs but
    // rendered 18, leaving the extra nodes at one fallback coordinate and
    // making them appear stacked in the center.
    const positionIds = new Set(canvasEntities.map(entity => entity.id));
    const pairLimit = mode === "all" ? 36 : focus ? 24 : 10;
    // An empty issue filter means there are no flagged relations for this
    // focus, not that the focus has no relationships. Keep the graph useful
    // by falling back to the complete focused set while the cards remain
    // empty and accurately report that there is nothing to review.
    const graphPairs = visiblePairs.length ? visiblePairs : focusPairs;
    const shownPairs = graphPairs.filter(pair => positionIds.has(pair.source.id) && positionIds.has(pair.target.id)).slice(0, pairLimit);
    const shownIds = new Set(shownPairs.flatMap(pair => [pair.source.id, pair.target.id]));
    const elements = [
      ...entities.filter(entity => shownIds.has(entity.id)).map(entity => ({ data: { id: String(entity.id), label: entity.is_unresolved ? "미확인 대상" : entity.name, type: entity.type, image: assetForEntity(entity) ?? "", unresolved: entity.is_unresolved ? 1 : 0 }, position: positions.get(entity.id) ?? { x: 400, y: 210 }, classes: `${entity.id === selectedEntityId ? "center " : ""}${assetForEntity(entity) ? "has-image" : ""}` })),
      ...shownPairs.map(pair => ({ data: { id: `r-${pair.key}`, relationId: pair.members[0].id, source: String(pair.source.id), target: String(pair.target.id), label: pair.members[0].display_label || pair.members[0].type }, classes: `${pair.members.some(needsReview) ? "issue " : ""}${pair.members.some(member => member.id === selectedRelationId) ? "selected" : ""}` })),
    ];
    const cy = cytoscape({ container: canvasRef.current, elements, userZoomingEnabled: true, userPanningEnabled: true, boxSelectionEnabled: false, minZoom: 0.35, maxZoom: 2.5, style: [
      { selector: "node", style: { "background-color": "#E6EFEB", "border-color": "#24635B", "border-width": "2", "label": "data(label)", "color": "#252A27", "font-size": "13", "font-weight": 700, "text-valign": "center", "text-halign": "center", "width": "72", "height": "60", "text-wrap": "wrap", "text-max-width": "96", "line-height": 1.2 } },
      { selector: "node[type='character']", style: { "width": 78, "height": 78, "background-color": "#D8EAE4" } },
      { selector: "node[type='place']", style: { "background-color": "#DCE8F2", "border-color": "#4F817D" } },
      { selector: "node[type='organization']", style: { "background-color": "#F2E3C8", "border-color": "#8A5A20" } },
      { selector: "node[type='item']", style: { "background-color": "#F3E6D2", "border-color": "#B78343" } },
      { selector: "node[type='event']", style: { "background-color": "#E9E2D5", "border-color": "#7B6B4B" } },
      { selector: "node[type='rule']", style: { "background-color": "#DDEBE4", "border-color": "#39796E" } },
      { selector: "node[type='foreshadowing']", style: { "background-color": "#E2E8F4", "border-color": "#6687BD" } },
      { selector: "node.has-image", style: { "shape": "round-rectangle", "background-image": "data(image)", "background-fit": "cover", "background-clip": "node", "width": 76, "height": 76, "border-width": 3, "text-valign": "bottom", "text-margin-y": 11, "text-background-color": "#FFFDF8", "text-background-opacity": 0.9, "text-background-padding": "3" } },
      { selector: "node.has-image[type='place']", style: { "width": 94, "height": 66 } },
      { selector: "node.has-image[type='item']", style: { "width": 74, "height": 66 } },
      { selector: "node.center", style: { "background-color": "#24635B", "color": "#FFFDF8", "border-width": 4, "width": 88, "height": 88 } },
      { selector: "node.center.has-image", style: { "color": "#252A27", "background-color": "#FFFDF8", "text-background-color": "#FFFDF8", "text-background-opacity": 0.95, "border-color": "#24635B" } },
      { selector: "node[unresolved=1]", style: { "border-style": "dashed", "border-color": "#AD443B", "background-color": "#FFF0EE", "color": "#AD443B" } },
      { selector: "edge", style: { "line-color": "#A7B5AF", "width": 2, "curve-style": "bezier", "target-arrow-shape": "triangle", "target-arrow-color": "#A7B5AF", "label": "" } },
      { selector: "edge.issue", style: { "line-color": "#AD443B", "target-arrow-color": "#AD443B", "line-style": "dashed", "width": 3 } },
      { selector: "edge.selected", style: { "line-color": "#24635B", "target-arrow-color": "#24635B", "width": "5", "label": "data(label)", "font-size": "12", "color": "#626B65", "text-background-color": "#FFFDF8", "text-background-opacity": 1, "text-background-padding": "3" } },
    ], layout: { name: "preset", animate: false, fit: false } as cytoscape.LayoutOptions });
    cy.on("tap", "node", event => selectEntity(entityById.get(Number(event.target.id())) ?? null));
    cy.on("tap", "edge", event => onSelectRelation?.(Number(event.target.data("relationId"))));
    cy.on("tap", event => { if (event.target === cy) { onSelectRelation?.(null); } });
    cyRef.current = cy;
    return () => { cy.destroy(); cyRef.current = null; };
  }, [entities, entityById, focus, mode, onSelectEntity, onSelectRelation, positions, selectedEntityId, selectedRelationId, visiblePairs]);
  return <div className="relationship-explorer">
    {reviewIssue && <section className="surface" aria-label="검토 후보의 관계와 근거"><span className="badge">{judgmentLabel[reviewIssue.status]}</span><h2>{reviewIssue.title}</h2>{!compactReview && <p>{reviewIssue.description}</p>}<p>원문 근거를 공유하는 관련 관계 {reviewRelations.length}개입니다. 모든 연결이 오류라는 뜻은 아닙니다.</p><button onClick={onBackReview}>검토 결과로 돌아가 판단 변경</button><button onClick={onCloseReview}>검토 범위 해제</button><details open={compactReview ? undefined : true}><summary>{compactReview ? '분석 설명과 원문 근거 펼치기' : '원문 근거 비교'}</summary>{compactReview && <p>{reviewIssue.description}</p>}<div className="review-source-comparison">{reviewEvidence.filter(chunk => reviewFocus?.chunkId == null || chunk.id === reviewFocus.chunkId).map(chunk => <article className="source-card" key={chunk.id}><blockquote>{chunk.text}</blockquote><button onClick={() => onOpenEvidence?.(chunk.document_id, chunk.text)}>이 근거 원고 열기</button></article>)}</div></details>{!reviewRelations.length && <p role="status">이 근거에 연결된 관계가 아직 없습니다. 원문에서 검토할 수 있으며, 관계를 새로 추출하려면 재분석이 필요합니다.</p>}</section>}

    <div className="explorer-toolbar">
      <div><span className="network-eyebrow">RELATIONSHIP EXPLORER</span><h2>{focus ? `${entityLabel(focus)}의 관계` : "이야기의 연결"}</h2><p>{focus ? `직접 연결 ${focusPairs.length}개 · 관계를 선택하면 원문 근거를 확인합니다.` : `${entities.length}개 대상 · ${pairs.length}개 관계 그룹을 탐색합니다.`}</p></div>
      <label className="explorer-search"><span>검색</span><input value={query} onChange={event => setQuery(event.target.value)} placeholder="인물·아이템·규칙 검색" /></label>
    </div>
    {graph.relations.some(relation => relation.has_unresolved_endpoint) && <p role="status" className="network-alert">연결 확인이 필요한 분석 결과가 있습니다. 미확인 대상과 점선 관계를 선택해 원문을 확인하세요. AI 추출 누락일 수 있으며 작가의 설정 오류로 확정하지 않습니다.</p>}
    <div className="explorer-modes" role="tablist" aria-label="관계 탐색 방식">
      <button role="tab" aria-selected={mode === "focus"} className={mode === "focus" ? "active" : ""} onClick={() => setMode("focus")}>중심 탐색</button>
      <button role="tab" aria-selected={mode === "issues"} className={mode === "issues" ? "active" : ""} onClick={() => setMode("issues")}>문제 점검 <b>{issueCount}</b></button>
      <button role="tab" aria-selected={mode === "timeline"} className={mode === "timeline" ? "active" : ""} onClick={() => setMode("timeline")}>회차 흐름</button>
      <button role="tab" aria-selected={mode === "all"} className={mode === "all" ? "active" : ""} onClick={() => setMode("all")}>전체 구조</button>
      {focus && <button className="subtle" onClick={() => selectEntity(null)}>중심 해제</button>}
    </div>
    <div className="explorer-grid">
      <section className="explorer-canvas" aria-label="관계 탐색 지도">
        <div className="explorer-canvas-head"><strong>{focus ? "직접 연결 관계" : "핵심 관계 미리보기"}</strong><span>확인 {canvasConfirmedCount} · 점검 {canvasIssueCount}</span></div>
        {canvasEntities.length ? <div ref={canvasRef} role="img" aria-label="선택 대상 중심 관계 지도" className={`explorer-cytoscape ${visiblePairs.length <= 4 ? "compact" : ""}`}/> : <div className="explorer-empty">조건에 맞는 관계가 없습니다.</div>}
        <div className="explorer-legend"><span><i className="confirmed"/>확인된 관계</span><span title="근거가 없거나 관계 신뢰도가 낮은 연결"><i className="issue"/>점검 필요 · 관련 검토/근거 부족</span><span>노드를 누르면 중심이 바뀝니다</span></div>
        {mode === "timeline" && timelineChapters.length > 1 && <div className="explorer-timeline" aria-label="회차별 관계 흐름">
          <div><strong>회차별 관계 흐름</strong><span>{timelineChapter === null ? "전체 회차" : `${timelineChapter + 1}화까지`}</span><button type="button" onClick={() => setTimelineChapter(null)} disabled={timelineChapter === null}>전체 보기</button></div>
          <input type="range" min={timelineChapters[0]} max={timelineChapters[timelineChapters.length - 1]} value={timelineChapter ?? timelineChapters[timelineChapters.length - 1]} onChange={event => setTimelineChapter(Number(event.target.value))} aria-label="표시 회차" />
          <small>{timelineChapters[0] + 1}화 · 관계가 생기거나 바뀐 시점만 누적해서 봅니다 · 언급이 없다고 단절로 확정하지 않습니다</small>
        </div>}
      </section>
      <aside className="explorer-inspector"><div className="inspector-heading"><strong>{focus ? "중심 대상" : "중심 대상 선택"}</strong><select aria-label="중심 대상 선택" value={selectedEntityId ?? ""} onChange={event => selectEntity(entityById.get(Number(event.target.value)) ?? null)}><option value="">대상 선택</option>{entityGroups.map(([type, items]) => <optgroup key={type} label={typeLabel[type] ?? type}>{items.map(entity => <option key={entity.id} value={entity.id}>{entityLabel(entity)}</option>)}</optgroup>)}</select></div>{focus ? <><span className="inspector-type">{focus.is_unresolved ? "미확인 대상 · 분석 확인 필요" : typeLabel[focus.type]} · {focus.document_count}개 회차</span><h3>{entityLabel(focus)}</h3><p>{focus.summary || "추출된 요약이 없습니다."}</p><div className="inspector-stats"><strong>{focusPairs.length}<small>관계 그룹</small></strong><strong>{focus.mention_count}<small>언급 횟수</small></strong></div></> : <div className="inspector-empty">인물이나 아이템을 선택하면 직접 연결 관계와 근거를 이곳에서 설명합니다.</div>}{selectedRelation && selectedPair && <div className="inspector-relation"><span className="inspector-type">선택한 관계</span><h3>{entityLabel(selectedPair.source)} → {entityLabel(selectedPair.target)}</h3><strong>{selectedRelation.display_label || selectedRelation.type}</strong><p>{selectedRelation.claims?.[0]?.explanation || "원문에서 추출된 관계 후보입니다."}</p><small>원문 근거 {selectedRelation.evidence_chunk_ids.length}개 · {selectedRelation.has_unresolved_endpoint ? "대상 연결 미확인" : `신뢰도 ${Math.round(selectedRelation.confidence * 100)}%`}</small>{selectedRelation.claims?.[0]?.quotes?.[0] && <button type="button" className="evidence-link" onClick={() => onOpenEvidence?.(selectedRelation.claims![0].quotes[0].document_id, selectedRelation.claims![0].quotes[0].quote)}>원문에서 근거 보기 · {selectedRelation.claims[0].quotes[0].chapter_index + 1}화</button>}{needsReview(selectedRelation) && <><p className="inspector-review-hint">점검 필요 관계입니다. 원문을 확인한 뒤 검토 결과에서 작가 판단을 선택하세요.</p><button type="button" className="primary" onClick={() => onReviewRelation?.(selectedRelation.id)}>검토 결과에서 판단하기</button></>}</div>}</aside>
    </div>
    <section className="explorer-relations"><div className="explorer-section-head"><div><span className="network-eyebrow">RELATION CARDS</span><h3>{mode === "timeline" ? "회차별 관계 흐름" : mode === "issues" ? "점검이 필요한 관계" : "관계와 원문 근거"}</h3></div><span>{visiblePairs.length}개 그룹</span></div>{renderedPairs.map(pair => { const representative = [...pair.members].sort((a, b) => (b.evidence_chunk_ids.length - a.evidence_chunk_ids.length) || b.confidence - a.confidence)[0]; const issue = pair.members.some(needsReview); return <button type="button" key={pair.key} className={`relation-card ${issue ? "issue" : ""} ${pair.members.some(member => member.id === selectedRelationId) ? "selected" : ""}`} onClick={() => onSelectRelation?.(representative.id)}><span className="relation-card-top"><b>{entityLabel(pair.source)} <em>→</em> {entityLabel(pair.target)}</b><small>{pair.members.length}개 주장</small></span><strong>{representative.display_label || representative.type}</strong>{[...new Map(pair.members.flatMap(member => relationJudgments(member, graph.issues ?? [])).map(issue => [issue.id, issue])).values()].map(issue => <span className="badge" key={issue.id}>관련 검토 · {judgmentLabel[issue.status]}</span>)}<p>{representative.claims?.[0]?.explanation || "원문에서 추출된 관계 후보입니다."}</p><span className="relation-meta">{issue ? "확인 필요" : "근거 확인"} · 근거 {representative.evidence_chunk_ids.length}개 · {representative.has_unresolved_endpoint ? "대상 연결 미확인" : `신뢰도 ${Math.round(representative.confidence * 100)}%`}{mode === "timeline" && (pairChapters.get(pair.key)?.length ?? 0) > 0 ? ` · ${(pairChapters.get(pair.key)![0] ?? 0) + 1}화부터` : ""}</span></button>; })}{visiblePairs.length > 12 && <button type="button" className="relation-more" onClick={() => setShowAllRelations(value => !value)}>{showAllRelations ? "핵심 관계만 보기" : `관계 ${visiblePairs.length - 12}개 더 보기`}</button>}{!visiblePairs.length && <div className="explorer-empty relation-empty">관계 카드가 없습니다. 검색어나 점검 범위를 바꿔보세요.</div>}</section>
  </div>;
}

export default RelationshipExplorer;
