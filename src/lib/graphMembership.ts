import type { EntityNode, GraphPayload, RelationEdge } from "./types";

const MEMBERSHIP_RELATION_PATTERN =
  /소속|조직|구성원|대표|멤버|관할|산하|휘하|본부|거점|소속된|속한|member|leader|belongs|works|contains|affiliated|under/i;

export function isMembershipRelation(relation: RelationEdge) {
  return MEMBERSHIP_RELATION_PATTERN.test(`${relation.type} ${relation.display_label}`);
}

export function buildOrganizationMembership(
  graph: GraphPayload,
  entitiesById: Map<number, EntityNode>,
) {
  const membershipByOrganizationId = new Map<number, Set<number>>();
  const parentOrganizationByEntityId = new Map<number, number>();
  for (const entity of graph.entities) {
    if (entity.type === "organization") {
      membershipByOrganizationId.set(entity.id, new Set());
    }
  }

  const membershipRelations = graph.relations
    .filter(isMembershipRelation)
    .sort(
      (left, right) =>
        (right.strength ?? right.confidence ?? 0) - (left.strength ?? left.confidence ?? 0),
    );

  const assignMember = (organizationId: number, memberId: number) => {
    if (organizationId === memberId || !membershipByOrganizationId.has(organizationId)) {
      return;
    }
    const member = entitiesById.get(memberId);
    if (!member || member.type === "organization" || parentOrganizationByEntityId.has(memberId)) {
      return;
    }
    membershipByOrganizationId.get(organizationId)?.add(memberId);
    parentOrganizationByEntityId.set(memberId, organizationId);
  };

  for (const relation of membershipRelations) {
    const source = entitiesById.get(relation.source_entity_id);
    const target = entitiesById.get(relation.target_entity_id);
    if (!source || !target) {
      continue;
    }
    if (source.type === "organization") {
      assignMember(source.id, target.id);
    }
    if (target.type === "organization") {
      assignMember(target.id, source.id);
    }
  }

  return { membershipByOrganizationId, parentOrganizationByEntityId };
}
