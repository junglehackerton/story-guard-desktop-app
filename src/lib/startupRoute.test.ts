import { describe, expect, it } from "vitest";
import { startupRoute } from "./startupRoute";

describe("startup route", () => {
  it("opens the shelf for a returning writer", () => {
    expect(startupRoute(true)).toBe("projects");
  });

  it("opens the guide only when no project is stored", () => {
    expect(startupRoute(false)).toBe("welcome");
  });
});
