import { describe, expect, it } from "vitest";

import { MEMBERSHIP_EDGE_STYLE, buildObsidianPositions, countVisibleTimelinePairs, entityVisual, graphHealthLevel, graphPanOffset, trackpadZoomFactor } from "./GraphView";
import { partitionRelationships } from "../lib/relationshipLayout";
import { buildOrganizationMembership, isMembershipRelation } from "../lib/graphMembership";
import type { EntityNode, GraphPayload, RelationEdge } from "../lib/types";

function entity(id: number, type: EntityNode["type"], name: string): EntityNode {
  return {
    id,
    project_id: 1,
    type,
    name,
    aliases: [],
    summary: "",
    first_seen_document_id: 1,
    mention_count: 1,
    document_ids: [1],
    document_count: 1,
    last_seen_document_id: 1,
    appearance_state: "active",
    visual_weight: 0.7,
  };
}

function relation(id: number, source: number, target: number, type: string): RelationEdge {
  return {
    id,
    project_id: 1,
    source_entity_id: source,
    target_entity_id: target,
    type,
    confidence: 0.86,
    evidence_chunk_ids: [1],
    strength: 0.8,
    is_weak: false,
    is_recent: true,
    display_label: type,
  };
}

function graphFixture(payload: Pick<GraphPayload, "entities" | "relations">): GraphPayload {
  return {
    ...payload,
    issues: [],
    changes: [],
    range: {
      start_chapter: null,
      end_chapter: null,
      document_ids: [1],
      document_count: 1,
      continuity_ready: true,
      message: "테스트 범위",
    },
  };
}

describe("organization graph membership", () => {
  const cleanHealth = {
    explicit_break_count: 0, conflicting_pair_count: 0, dangling_relation_count: 0,
    isolated_entity_count: 0, unsupported_relation_count: 0, generic_relation_count: 0,
    changed_relation_count: 0, gap_relation_count: 0, component_count: 1,
  };

  it("prioritizes hard breaks over review warnings in the health summary", () => {
    expect(graphHealthLevel(cleanHealth)).toBe("good");
    expect(graphHealthLevel({ ...cleanHealth, gap_relation_count: 1 })).toBe("warn");
    expect(graphHealthLevel({ ...cleanHealth, dangling_relation_count: 1, gap_relation_count: 1 })).toBe("danger");
  });

  it("scales visual emphasis with relationship degree and preserves dormant state", () => {
    const core = entity(1, "character", "중심 인물");
    const dormant = { ...entity(2, "rule", "휴면 규칙"), appearance_state: "dormant" as const };
    expect(entityVisual(core, 8, 12).size).toBeGreaterThan(entityVisual(core, 0, 12).size);
    expect(entityVisual(dormant, 2, 12).opacity).toBeLessThan(1);
  });

  it("removes dangling endpoints from the drawable network while preserving valid candidates", () => {
    const graph = graphFixture({
      entities: [entity(1, "character", "도윤"), entity(2, "item", "봉인검")],
      relations: [relation(1, 1, 2, "소유/사용"), relation(2, 1, 99, "관계")],
    });
    const partition = partitionRelationships(graph);
    expect(partition.network.relations.map(edge => edge.id)).toEqual([1]);
    expect(partition.network.entities.map(node => node.id)).toEqual([1, 2]);
    expect(partition.unlinked).toEqual([]);
  });

  it("treats organization scope relations as set containment", () => {
    const graph = graphFixture({
      entities: [
        entity(1, "organization", "백야단"),
        entity(2, "character", "한서윤"),
        entity(3, "place", "흑월성"),
        entity(4, "event", "서고 봉쇄 사건"),
      ],
      relations: [
        relation(1, 1, 2, "소속/조직"),
        relation(2, 1, 3, "본부/거점"),
        relation(3, 1, 4, "관할"),
      ],
    });
    const entitiesById = new Map(graph.entities.map((node) => [node.id, node]));

    const membership = buildOrganizationMembership(graph, entitiesById);

    expect(membership.membershipByOrganizationId.get(1)).toEqual(new Set([2, 3, 4]));
    expect(membership.parentOrganizationByEntityId).toEqual(
      new Map([
        [2, 1],
        [3, 1],
        [4, 1],
      ]),
    );
  });

  it("does not treat ordinary conflict as containment", () => {
    expect(isMembershipRelation(relation(1, 1, 2, "적대/의심"))).toBe(false);
  });

  it("keeps organization membership relations visible as graph lines", () => {
    expect(Object.prototype.hasOwnProperty.call(MEMBERSHIP_EDGE_STYLE, "display")).toBe(false);
    expect(Number(MEMBERSHIP_EDGE_STYLE.opacity)).toBeGreaterThan(0);
  });

  it("keeps timeline health counts aligned with drawable relation pairs", () => {
    const graph = graphFixture({
      entities: [entity(1, "character", "유나"), entity(2, "item", "봉인검")],
      relations: [relation(10, 1, 2, "사용")],
    });
    graph.timeline = [
      { source_entity_id: 1, target_entity_id: 2, source_name: "유나", target_name: "봉인검", relation_type: "사용", chapter_index: 0, document_id: 1, evidence_chunk_ids: [], status: "changed" },
      { source_entity_id: 1, target_entity_id: 99, source_name: "유나", target_name: "없는 대상", relation_type: "변화", chapter_index: 1, document_id: 1, evidence_chunk_ids: [], status: "changed" },
    ];
    expect(countVisibleTimelinePairs(graph, "changed")).toBe(1);
  });

  it("maps modified trackpad wheel deltas to directional zoom", () => {
    expect(trackpadZoomFactor(-120)).toBeGreaterThan(1);
    expect(trackpadZoomFactor(120)).toBeLessThan(1);
    expect(trackpadZoomFactor(Number.NaN)).toBe(1);
  });

  it("pans the SVG in the same direction as a map drag", () => {
    expect(graphPanOffset({ x: 0, y: 0 }, { x: 100, y: -50 }, { width: 1000, height: 500 }, { width: 2000, height: 1000 }, 1)).toEqual({ x: -200, y: 100 });
  });

  it("keeps a drag inside the map bounds and tolerates invalid scale", () => {
    expect(graphPanOffset({ x: 0, y: 0 }, { x: -100_000, y: 100_000 }, { width: 1000, height: 500 }, { width: 2000, height: 1000 }, 1)).toEqual({ x: 500, y: -250 });
    expect(graphPanOffset({ x: 0, y: 0 }, { x: 20, y: 20 }, { width: 1000, height: 500 }, { width: 2000, height: 1000 }, Number.NaN)).toEqual({ x: -40, y: -40 });
  });

  it("places organization domains with enough room between their member clusters", () => {
    const graph = graphFixture({
      entities: [
        entity(1, "organization", "백야단"),
        entity(2, "character", "한서윤"),
        entity(3, "place", "흑월성"),
        entity(4, "event", "서고 봉쇄 사건"),
        entity(5, "organization", "청운 감찰청"),
        entity(6, "character", "강도윤"),
        entity(7, "place", "청운청 본관"),
        entity(8, "rule", "감찰 기록 규칙"),
      ],
      relations: [
        relation(1, 1, 2, "소속/조직"),
        relation(2, 1, 3, "본부/거점"),
        relation(3, 1, 4, "관할"),
        relation(4, 5, 6, "소속/조직"),
        relation(5, 5, 7, "본부/거점"),
        relation(6, 5, 8, "관할"),
      ],
    });
    const entitiesById = new Map(graph.entities.map((node) => [node.id, node]));
    const degreeByEntityId = new Map(graph.entities.map((node) => [node.id, 0]));
    for (const edge of graph.relations) {
      degreeByEntityId.set(edge.source_entity_id, (degreeByEntityId.get(edge.source_entity_id) ?? 0) + 1);
      degreeByEntityId.set(edge.target_entity_id, (degreeByEntityId.get(edge.target_entity_id) ?? 0) + 1);
    }
    const membership = buildOrganizationMembership(graph, entitiesById);

    const positions = buildObsidianPositions(
      graph,
      entitiesById,
      membership.membershipByOrganizationId,
      membership.parentOrganizationByEntityId,
      degreeByEntityId,
    );
    const leftClusterX = [2, 3, 4].reduce((sum, entityId) => sum + (positions.get(entityId)?.x ?? 0), 0) / 3;
    const rightClusterX = [6, 7, 8].reduce((sum, entityId) => sum + (positions.get(entityId)?.x ?? 0), 0) / 3;

    expect(Math.abs(rightClusterX - leftClusterX)).toBeGreaterThan(620);
  });

  it("preserves a character's memberships in multiple organizations", () => {
    const graph = graphFixture({
      entities: [entity(1, "organization", "백야단"), entity(2, "organization", "청운청"), entity(3, "character", "한서윤")],
      relations: [relation(1, 1, 3, "소속/조직"), relation(2, 2, 3, "소속/조직")],
    });
    const entitiesById = new Map(graph.entities.map((node) => [node.id, node]));
    const membership = buildOrganizationMembership(graph, entitiesById);
    expect(membership.membershipByOrganizationId.get(1)).toEqual(new Set([3]));
    expect(membership.membershipByOrganizationId.get(2)).toEqual(new Set([3]));
  });
});
