import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AnalysisProgressPanel } from "./AnalysisProgressPanel";
import type { AnalysisJob } from "../lib/types";

describe("AnalysisProgressPanel", () => {
  it("renders the current LLM analysis step with progress", () => {
    const job: AnalysisJob = {
      id: 7,
      project_id: 3,
      status: "running",
      current_step: "extract",
      progress: 42,
      message: "LLM이 인물, 장소, 조직, 아이템, 사건, 규칙, 떡밥을 추출 중입니다.",
      created_at: "2026-06-20 00:00:00",
      updated_at: "2026-06-20 00:00:01",
    };

    const html = renderToStaticMarkup(<AnalysisProgressPanel job={job} />);

    expect(html).toContain("LLM 분석 진행 중");
    expect(html).toContain("엔티티 추출");
    expect(html).toContain("42%");
    expect(html).toContain('aria-valuenow="42"');
  });

  it("renders a failed analysis state", () => {
    const job: AnalysisJob = {
      id: 8,
      project_id: 3,
      status: "failed",
      current_step: "failed",
      progress: 100,
      message: "로컬 LLM 모델이 준비되지 않았습니다.",
      created_at: "2026-06-20 00:00:00",
      updated_at: "2026-06-20 00:00:01",
    };

    const html = renderToStaticMarkup(<AnalysisProgressPanel job={job} />);

    expect(html).toContain("분석 실패");
    expect(html).toContain("로컬 LLM 모델이 준비되지 않았습니다.");
  });
});
