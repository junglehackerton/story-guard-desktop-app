import type { EntityType, IssueStatus } from "./types";

export const ENTITY_TYPE_LABELS: Record<EntityType, string> = {
  character: "인물",
  place: "장소",
  organization: "조직",
  item: "아이템",
  event: "사건",
  rule: "규칙",
  foreshadowing: "떡밥",
};

export const ISSUE_STATUS_LABELS: Record<IssueStatus, string> = {
  open: "열림",
  accepted: "확정",
  ignored: "무시",
  deferred: "보류",
};

export const ISSUE_CATEGORY_LABELS: Record<string, string> = {
  timeline: "시간선",
  character_state: "인물 상태",
  world_rule: "세계 규칙",
  relationship: "관계",
  unresolved_foreshadowing: "미회수 떡밥",
  contradiction: "설정 충돌",
};
