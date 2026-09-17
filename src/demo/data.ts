import snapshot from './snapshot.json';
import type { GraphPayload, Project, StoryDocument, EvidenceChunk, IssueStatus, ForeshadowingStatusValue } from '../lib/types';
export const sample = snapshot as unknown as {
  version: string; provenance: string; project: Project; documents: StoryDocument[];
  chunks: EvidenceChunk[]; graph: GraphPayload;
};
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
