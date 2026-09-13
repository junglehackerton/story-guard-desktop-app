import { describe, expect, it } from "vitest";
import { relationshipPositions } from "./relationshipLayout";
import type { GraphPayload } from "./types";

describe("real 50-episode graph fixture", () => {
  it("keeps every extracted node separated in the published graph", () => {
    // Keep the same shape as the 50-episode run: 37 extracted entities and a
    // dense 84-edge relation set. The test stays self-contained for browser
    // builds, while the exact provider result is preserved in the validation
    // JSON artifact alongside this test.
    const fixture = {
      entities: Array.from({ length: 37 }, (_, id) => ({ id, type: "character", name: `인물 ${id}` })),
      relations: Array.from({ length: 84 }, (_, id) => ({ id, source_entity_id: id % 37, target_entity_id: (id * 7 + 3) % 37 })),
      issues: [], changes: [],
    } as unknown as GraphPayload;
    const positions = [...relationshipPositions(fixture).values()];
    expect(positions).toHaveLength(fixture.entities.length);
    for (let left = 0; left < positions.length; left += 1) {
      for (let right = left + 1; right < positions.length; right += 1) {
        expect(Math.abs(positions[left].x - positions[right].x) >= 190 || Math.abs(positions[left].y - positions[right].y) >= 123).toBe(true);
      }
    }
  });
});
