import { expect, it } from "vitest";
import { countConnectedComponents, countDanglingRelations, isDanglingRelation, isRelationshipHealthIssue, relationPairKey, relationTypesConflict, relationshipComponents, temporalIssuePairs, timelinePairsByStatus } from "./relationshipHealth";
import type { GraphPayload, RelationEdge } from "./types";

const relation = (source_entity_id: number, target_entity_id: number, type = "동행/협력", id = 1) => ({
  id, project_id: 1, source_entity_id, target_entity_id, type,
  confidence: 0.9, evidence_chunk_ids: [1], strength: 0.9, is_weak: false,
  is_recent: false, display_label: type,
} as RelationEdge);

it("uses an order-independent pair key", () => {
  expect(relationPairKey(8, 3)).toBe("3:8");
  expect(relationPairKey(3, 8)).toBe("3:8");
});

it("flags opposing semantic labels while leaving ordinary state changes alone", () => {
  expect(relationTypesConflict(["계약 체결", "계약 거절"])).toBe(true);
  expect(relationTypesConflict(["보호함", "적대/의심"])).toBe(true);
  expect(relationTypesConflict(["계약 체결", "계약 해지"])).toBe(true);
  expect(relationTypesConflict(["등장", "이동"])).toBe(false);
});

it("identifies a missing endpoint without dropping the relation", () => {
  const ids = new Set([3, 8]);
  expect(isDanglingRelation(relation(3, 99), ids)).toBe(true);
  expect(isDanglingRelation(relation(8, 3), ids)).toBe(false);
});

it("counts dangling relations from the displayed graph scope", () => {
  const graph = {
    entities: [{ id: 3 }, { id: 8 }],
    relations: [relation(3, 8), relation(3, 99)],
    issues: [], changes: [], range: {} as never,
  } as unknown as GraphPayload;
  expect(countDanglingRelations(graph)).toBe(1);
});

it("keeps persisted unresolved endpoints visible as diagnostics", () => {
  const edge = { ...relation(3, 8), has_unresolved_endpoint: true };
  const graph = { entities: [{ id: 3 }, { id: 8, is_unresolved: true }],
    relations: [edge], issues: [], changes: [] } as unknown as GraphPayload;
  expect(isDanglingRelation(edge, new Set([3, 8]))).toBe(true);
  expect(countDanglingRelations(graph)).toBe(1);
});

it("counts only valid connected relationship islands", () => {
  const graph = {
    entities: [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }, { id: 5 }],
    relations: [relation(1, 2), relation(3, 4), relation(4, 99)],
    issues: [], changes: [], range: {} as never,
  } as unknown as GraphPayload;
  expect(countConnectedComponents(graph)).toBe(2);
});

it("returns deterministic component members and excludes dangling diagnostics", () => {
  const graph = {
    entities: [{ id: 8 }, { id: 3 }, { id: 4 }, { id: 9 }],
    relations: [relation(8, 3, "동행/협력", 11), relation(4, 9, "동행/협력", 12), relation(3, 99, "관계", 13)],
    issues: [], changes: [], range: {} as never,
  } as unknown as GraphPayload;
  expect(relationshipComponents(graph)).toEqual([
    { entityIds: [3, 8], relationIds: [11], anchorId: 3 },
    { entityIds: [4, 9], relationIds: [12], anchorId: 4 },
  ]);
});

it("chooses the highest-degree anchor and keeps every edge in a component", () => {
  const graph = {
    entities: [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }],
    relations: [
      relation(1, 2, "동행/협력", 21),
      relation(2, 3, "보호", 22),
      relation(2, 4, "소유/사용", 23),
    ],
    issues: [], changes: [], range: {} as never,
  } as unknown as GraphPayload;
  expect(relationshipComponents(graph)).toEqual([
    { entityIds: [1, 2, 3, 4], relationIds: [21, 22, 23], anchorId: 2 },
  ]);
});

it("keeps changed and explicitly broken relations in health view", () => {
  const graph = {
    entities: [], relations: [], issues: [], changes: [], range: {} as never,
    timeline: [
      { source_entity_id: 3, target_entity_id: 8, source_name: "A", target_name: "B", relation_type: "관계 해제", chapter_index: 2, document_id: 3, evidence_chunk_ids: [], status: "explicit_break" },
      { source_entity_id: 4, target_entity_id: 9, source_name: "C", target_name: "D", relation_type: "적대/의심", chapter_index: 3, document_id: 4, evidence_chunk_ids: [], status: "changed" },
    ],
  } as GraphPayload;
  const pairs = temporalIssuePairs(graph);
  expect(isRelationshipHealthIssue(relation(8, 3, "관계 해제"), pairs)).toBe(true);
  expect(isRelationshipHealthIssue(relation(9, 4), pairs)).toBe(true);
  expect(isRelationshipHealthIssue(relation(1, 2), pairs)).toBe(false);
});

it("counts each temporal pair once across multiple chapter events", () => {
  const graph = {
    entities: [], relations: [], issues: [], changes: [], range: {} as never,
    timeline: [
      { source_entity_id: 3, target_entity_id: 8, source_name: "A", target_name: "B", relation_type: "변화", chapter_index: 1, document_id: 2, evidence_chunk_ids: [], status: "changed" },
      { source_entity_id: 8, target_entity_id: 3, source_name: "B", target_name: "A", relation_type: "변화", chapter_index: 2, document_id: 3, evidence_chunk_ids: [], status: "changed" },
      { source_entity_id: 3, target_entity_id: 8, source_name: "A", target_name: "B", relation_type: "관계 해제", chapter_index: 3, document_id: 4, evidence_chunk_ids: [], status: "explicit_break" },
    ],
  } as GraphPayload;
  expect(timelinePairsByStatus(graph, "changed").size).toBe(1);
  expect(timelinePairsByStatus(graph, "explicit_break").size).toBe(1);
});

it("keeps a middle-chapter gap as a review signal", () => {
  const graph = {
    entities: [], relations: [], issues: [], changes: [], range: {} as never,
    timeline: [
      { source_entity_id: 3, target_entity_id: 8, source_name: "A", target_name: "B", relation_type: "동행/협력", chapter_index: 0, document_id: 1, evidence_chunk_ids: [], status: "observed" },
      { source_entity_id: 3, target_entity_id: 8, source_name: "A", target_name: "B", relation_type: "동행/협력", chapter_index: 2, document_id: 3, evidence_chunk_ids: [], status: "gap" },
    ],
  } as GraphPayload;
  expect(timelinePairsByStatus(graph, "gap").size).toBe(1);
  expect(temporalIssuePairs(graph).has("3:8")).toBe(true);
});

it("infers a review gap when evidence jumps over a chapter without an explicit gap flag", () => {
  const graph = {
    entities: [], relations: [], issues: [], changes: [], range: {} as never,
    timeline: [
      { source_entity_id: 3, target_entity_id: 8, source_name: "A", target_name: "B", relation_type: "동행/협력", chapter_index: 0, document_id: 1, evidence_chunk_ids: [], status: "observed" },
      { source_entity_id: 3, target_entity_id: 8, source_name: "A", target_name: "B", relation_type: "동행/협력", chapter_index: 3, document_id: 4, evidence_chunk_ids: [], status: "observed" },
    ],
  } as GraphPayload;
  expect(timelinePairsByStatus(graph, "gap")).toEqual(new Set(["3:8"]));
});
