import { describe, expect, it } from 'vitest';
import { groupRelationshipEdges } from './relationshipGrouping';
import type { RelationEdge } from './types';

const edge = (overrides: Partial<RelationEdge>): RelationEdge => ({
  id: 1, project_id: 1, source_entity_id: 1, target_entity_id: 2, type: '동맹',
  display_label: '동맹', confidence: 0.7, evidence_chunk_ids: [], strength: 0.5,
  is_weak: false, is_recent: true, ...overrides,
});

describe('groupRelationshipEdges', () => {
  it('groups reversed pairs with the same meaning and aggregates evidence', () => {
    const groups = groupRelationshipEdges([
      edge({ id: 3, origin: 'local', evidence_chunk_ids: [10] }),
      edge({ id: 2, source_entity_id: 2, target_entity_id: 1, origin: 'gpt', evidence_chunk_ids: [11, 12], claims: [{ explanation: '확인', basis: 'explicit', quotes: [] }] }),
      edge({ id: 4, display_label: '적대', type: '적대' }),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0].representative.id).toBe(2);
    expect(groups[0].count).toBe(2);
    expect(groups[0].evidenceCount).toBe(3);
    expect(groups[0].origins).toEqual(new Set(['local', 'gpt']));
  });
});
