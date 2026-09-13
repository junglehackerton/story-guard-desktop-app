import { describe, expect, it } from "vitest";
import { friendlyStartupError } from "./startupError";
import { ApiRequestError } from './api';

describe("friendlyStartupError", () => {
  it("turns browser network errors into an actionable Korean message", () => {
    expect(friendlyStartupError(new Error("Failed to fetch"))).toContain("다시 확인");
  });

  it("explains expired local API authentication", () => {
    expect(friendlyStartupError(new Error("로컬 API 인증 토큰이 없습니다"))).toContain("인증이 만료");
  });

  it("keeps useful backend diagnostics", () => {
    expect(friendlyStartupError(new Error("backend가 시작되지 않았습니다"))).toBe("backend가 시작되지 않았습니다");
  });

  it('identifies the failing request and attempts without forcing a restart', () => {
    const message=friendlyStartupError(new ApiRequestError('로컬 API에 연결하지 못했습니다.','/settings','GET',3,'network'));
    expect(message).toContain('GET /settings');
    expect(message).toContain('3회 시도');
    expect(message).not.toContain('앱을 다시 실행');
  });
});
