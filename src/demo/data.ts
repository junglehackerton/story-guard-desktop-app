import snapshot from './snapshot.json';
import type { EntityNode, GraphPayload, Project, StoryDocument, EvidenceChunk, IssueStatus, ForeshadowingStatusValue } from '../lib/types';
type DemoSnapshot = {
  version: string; provenance: string; project: Project; documents: StoryDocument[];
  chunks: EvidenceChunk[]; graph: GraphPayload;
};
const rawSample = snapshot as unknown as DemoSnapshot;

/**
 * The source analysis contains both the formal name `윤해주` and the short
 * form `해주`. Keep the published demo internally consistent without running
 * another embedding/GPT pass: rewire graph references to the canonical node
 * and retain the short form as an alias.
 */
function normalizeDemoGraph(graph: GraphPayload): GraphPayload {
  const canonical = graph.entities.find(entity => entity.type === 'character' && entity.name === '윤해주');
  const duplicate = graph.entities.find(entity => entity.type === 'character' && entity.name === '해주');
  if (!canonical || !duplicate || canonical.id === duplicate.id) return graph;
  const merged: EntityNode = {
    ...canonical,
    aliases: [...new Set([...canonical.aliases, '해주', ...duplicate.aliases])],
    mention_count: canonical.mention_count + duplicate.mention_count,
    document_ids: [...new Set([...canonical.document_ids, ...duplicate.document_ids])],
    document_count: new Set([...canonical.document_ids, ...duplicate.document_ids]).size,
    visual_weight: Math.max(canonical.visual_weight, duplicate.visual_weight),
  };
  const remap = (id: number) => id === duplicate.id ? canonical.id : id;
  return {
    ...graph,
    entities: graph.entities.filter(entity => entity.id !== duplicate.id).map(entity => entity.id === canonical.id ? merged : entity),
    relations: graph.relations.map(relation => ({ ...relation, source_entity_id: remap(relation.source_entity_id), target_entity_id: remap(relation.target_entity_id) })),
    timeline: graph.timeline?.map(event => ({ ...event, source_entity_id: remap(event.source_entity_id), target_entity_id: remap(event.target_entity_id), source_name: event.source_entity_id === duplicate.id ? canonical.name : event.source_name, target_name: event.target_entity_id === duplicate.id ? canonical.name : event.target_name })),
  };
}

export const sample: DemoSnapshot = { ...rawSample, graph: normalizeDemoGraph(rawSample.graph) };
export const storageKey = `storyguard-demo-${sample.version}`;
export function loadJudgments(): Record<number, IssueStatus> {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey) || '{}');
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([id,status]) => sample.graph.issues.some(i => i.id === Number(id)) && ['open','accepted','ignored','deferred'].includes(String(status)))) as Record<number, IssueStatus>;
  } catch { return {}; }
}

export const clueStorageKey = `${storageKey}-clues`;
export function loadClueJudgments(): Record<number, ForeshadowingStatusValue> {
  try {
    const value = JSON.parse(localStorage.getItem(clueStorageKey) || '{}');
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([id,status]) => sample.graph.entities.some(e => e.type==='foreshadowing' && e.id===Number(id)) && ['unreviewed','in_progress','resolved','intentional'].includes(String(status)))) as Record<number, ForeshadowingStatusValue>;
  } catch { return {}; }
}
