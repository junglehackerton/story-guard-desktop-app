import type { GraphPayload, RelationEdge, StoryDocument } from '../lib/types';

/** Order by manuscript chapter, never claim this is in-world chronology. */
export function relationshipAccount(edge: RelationEdge, graph: GraphPayload) {
  return graph.relations.filter(r =>
    (r.source_entity_id === edge.source_entity_id && r.target_entity_id === edge.target_entity_id) ||
    (r.target_entity_id === edge.source_entity_id && r.source_entity_id === edge.target_entity_id))
    .flatMap(r => (r.claims ?? []).map((claim, index) => ({relation:r, claim,index,
      chapter: Math.min(...claim.quotes.map(q=>q.chapter_index))})))
    .sort((a,b)=>a.chapter-b.chapter || a.relation.id-b.relation.id || a.index-b.index);
}
export function RelationStory({edge,graph,documents,onOpenDocument}: {
  edge:RelationEdge;graph:GraphPayload;documents:StoryDocument[];onOpenDocument:(id:number,quote?:string)=>void;
}) {
  const account=relationshipAccount(edge,graph);
  const names=new Map(graph.entities.map(e=>[e.id,e.name]));
  const entityName=(id:number)=>names.get(id)??`알 수 없는 대상 #${id}`;
  return <section className="relation-story" aria-label="관계 설명과 회차별 근거">
    <h3>관계를 설명하는 근거</h3>
    {!account.length?<p className="relation-missing">이전 분석에는 관계 설명과 정확한 인용문이 저장되지 않았습니다. 아래 원문을 확인하거나 새 GPT 분석으로 설명을 생성하세요.</p>:<>
      <p className="muted">원고의 회차 순서입니다. 사건의 시간 순서나 관계 변화 확정을 뜻하지 않습니다. 모든 설명은 작가 검토 전 후보입니다.</p>
      <ol>{account.map(({relation,claim,index})=><li key={`${relation.id}-${index}`} className={relation.id===edge.id?'current':''}>
        <span className={`claim-basis ${claim.basis}`}>{claim.basis==='explicit'?'직접 서술 근거 · AI 추출':'AI 해석 · 검토 필요'}</span>
        <h4>{entityName(relation.source_entity_id)} → {entityName(relation.target_entity_id)} · {relation.type}</h4>
        <p>{claim.explanation}</p>
        {claim.quotes.map((q,i)=><div className="claim-quote" key={`${q.chunk_id}-${i}`}>
          <button onClick={()=>onOpenDocument(q.document_id,q.quote)}>{q.chapter_index+1}화 · {documents.find(d=>d.id===q.document_id)?.title??'원문 열기'} ↗</button>
          <blockquote>{q.quote}</blockquote>
        </div>)}
      </li>)}</ol>
    </>}
  </section>;
}
