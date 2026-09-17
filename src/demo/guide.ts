import { sample } from './data';

// Curated excerpts from the shipped analysis, not generated demo responses.
// Tests require every excerpt to remain in both its evidence chunk and source.
export const guideIssueId = 70;
export const guideSources = [
  { chunkId: 3960, label: '3화 · 열쇠를 잘라 버림', quotes: [
    '해주는 열쇠를 꺼내 소형 절단기로 황동 몸통을 잘랐다. 딱, 작은 소리가 났다. 두 조각을 배수구에 흘려 넣었다. 녹색 머리가 어둠 속으로 사라졌다. 열여덟 번 사물함의 열쇠는 이제 쓸 수 없었다.',
  ] },
  { chunkId: 3983, label: '5화 · 같은 열쇠가 다시 등장', quotes: [
    '그리고 안주머니에서 녹색 머리의 황동 열쇠를 꺼냈다. 열여덟 번 사물함을 열 때 썼던 바로 그 열쇠였다.',
    '서령은 흠집 하나 없는 열쇠를 쥐었다.',
  ] },
  { chunkId: 3984, label: '5화 · 자물쇠를 여는 장면', quotes: [
    '세탁실의 형광등은 켜는 데 시간이 걸렸다. 서령은 열쇠를 두 번 놓쳤다. 해주는 대신 잡아 주지 않았다. 세 번째에는 자물쇠가 돌아갔다.',
  ] },
];

export function guideAvailable() {
  const issue = sample.graph.issues.find(i => i.id === guideIssueId);
  return !!issue && guideSources.every(source => {
    const chunk = sample.chunks.find(c => c.id === source.chunkId);
    const document = sample.documents.find(d => d.id === chunk?.document_id);
    return chunk && document && issue.evidence_chunk_ids.includes(chunk.id)
      && source.quotes.every(q => chunk.text.includes(q) && document.content.includes(q));
  });
}

export function evidenceChapters(entityId: number) {
  const entity = sample.graph.entities.find(e => e.id === entityId);
  const ids = new Set(entity?.document_ids ?? []);
  for (const relation of sample.graph.relations.filter(r => r.source_entity_id === entityId || r.target_entity_id === entityId)) {
    for (const id of relation.evidence_chunk_ids) {
      const chunk = sample.chunks.find(c => c.id === id);
      if (chunk) ids.add(chunk.document_id);
    }
    for (const claim of relation.claims ?? []) for (const quote of claim.quotes) ids.add(quote.document_id);
  }
  return sample.documents.filter(d => ids.has(d.id)).sort((a,b) => a.chapter_index-b.chapter_index);
}
