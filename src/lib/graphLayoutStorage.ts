import type { EntityNode } from "./types";

export type GraphPosition = { x: number; y: number };

const GRAPH_POSITION_STORAGE_PREFIX = "storyGuard.graphPositions.v2";

export function graphPositionsStorageKey(projectId: number) {
  return `${GRAPH_POSITION_STORAGE_PREFIX}.${projectId}`;
}

export function readGraphPositions(
  projectId: number | null,
  entities: EntityNode[],
): Map<number, GraphPosition> {
  if (!projectId || typeof window === "undefined") {
    return new Map();
  }
  const raw = window.localStorage.getItem(graphPositionsStorageKey(projectId));
  if (!raw) {
    return new Map();
  }
  const validEntityIds = new Set(entities.map((entity) => entity.id));
  try {
    const parsed = JSON.parse(raw) as Record<string, GraphPosition>;
    const positions = new Map<number, GraphPosition>();
    for (const [rawId, position] of Object.entries(parsed)) {
      const entityId = Number(rawId);
      if (
        validEntityIds.has(entityId) &&
        Number.isFinite(position?.x) &&
        Number.isFinite(position?.y)
      ) {
        positions.set(entityId, { x: position.x, y: position.y });
      }
    }
    return positions;
  } catch {
    return new Map();
  }
}

export function writeGraphPositions(
  projectId: number | null,
  positions: Map<number, GraphPosition>,
) {
  if (!projectId || typeof window === "undefined") {
    return;
  }
  const payload = Object.fromEntries(
    [...positions.entries()].map(([entityId, position]) => [
      String(entityId),
      { x: Math.round(position.x), y: Math.round(position.y) },
    ]),
  );
  window.localStorage.setItem(graphPositionsStorageKey(projectId), JSON.stringify(payload));
}

export function clearGraphPositions(projectId: number | null) {
  if (!projectId || typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(graphPositionsStorageKey(projectId));
}
