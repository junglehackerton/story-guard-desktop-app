import { describe, expect, it } from "vitest";

import appSource from "./App.tsx?raw";

describe("application close behavior", () => {
  it("does not intercept the native desktop close button", () => {
    expect(appSource).not.toContain("onCloseRequested");
    expect(appSource).not.toContain("beforeunload");
    expect(appSource).not.toContain("ExitAnalysisConfirmModal");
    expect(appSource).not.toContain("handleWindowCloseRequest");
  });
});
