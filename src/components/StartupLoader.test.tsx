import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { StartupLoader, type StartupStatus } from "./StartupLoader";

describe("StartupLoader", () => {
  it("renders the startup progress state", () => {
    const status: StartupStatus = {
      visible: true,
      mode: "loading",
      message: "Local AI 확인 중",
      detail: "로컬 LLM 런타임과 모델 파일을 확인하고 있습니다.",
      progress: 52,
    };

    const html = renderToStaticMarkup(<StartupLoader status={status} onRetry={vi.fn()} />);

    expect(html).toContain("시스템 로딩");
    expect(html).toContain("Local AI 확인 중");
    expect(html).toContain('aria-valuenow="52"');
  });

  it("renders the retry action for startup errors", () => {
    const status: StartupStatus = {
      visible: true,
      mode: "error",
      message: "초기 로딩 실패",
      detail: "데스크톱 backend가 시작되지 않았습니다.",
      progress: 100,
    };

    const html = renderToStaticMarkup(<StartupLoader status={status} onRetry={vi.fn()} />);

    expect(html).toContain("시작 실패");
    expect(html).toContain("데스크톱 backend가 시작되지 않았습니다.");
    expect(html).toContain("다시 확인");
  });
});
