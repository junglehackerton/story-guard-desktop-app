import { describe, expect, it } from "vitest";

import { MEMBERSHIP_EDGE_STYLE, buildObsidianPositions } from "./GraphView";
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
      continuity_ready: false,
      message: "테스트 범위",
    },
  };
}

describe("organization graph membership", () => {
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
});
