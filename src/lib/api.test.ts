import { afterEach, describe, expect, it, vi } from "vitest";

import { api, setApiToken } from "./api";

describe("api client", () => {
  afterEach(() => {
    setApiToken("");
    vi.unstubAllGlobals();
  });

  it("uses the local backend by default", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ status: "ok" })));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.health()).resolves.toEqual({ status: "ok" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/health",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
  });

  it("throws backend detail messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: "Local AI 연결 실패" }), {
            status: 503,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );

    await expect(api.health()).rejects.toThrow("Local AI 연결 실패");
  });

  it("adds the desktop api token when configured", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ status: "ok" })));
    vi.stubGlobal("fetch", fetchMock);
    setApiToken("desktop-token");

    await expect(api.ready()).resolves.toEqual({ status: "ok" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/health/ready",
      expect.objectContaining({
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-Story-Guard-Token": "desktop-token",
        }),
      }),
    );
  });

  it("shuts down the local backend with POST", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ status: "stopping" })));
    vi.stubGlobal("fetch", fetchMock);
    setApiToken("desktop-token");

    await expect(api.shutdown()).resolves.toEqual({ status: "stopping" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/shutdown",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "X-Story-Guard-Token": "desktop-token",
        }),
      }),
    );
  });

  it("updates project titles with PATCH", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            id: 7,
            title: "유리 종루의 밤",
            root_path: null,
            created_at: "2026-06-20 00:00:00",
            updated_at: "2026-06-20 00:00:00",
          }),
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.updateProjectTitle(7, "유리 종루의 밤")).resolves.toMatchObject({
      id: 7,
      title: "유리 종루의 밤",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/projects/7",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ title: "유리 종루의 밤" }),
      }),
    );
  });

  it("deletes documents with DELETE", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            project_id: 3,
          }),
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.deleteDocument(42)).resolves.toEqual({ project_id: 3 });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/documents/42",
      expect.objectContaining({
        method: "DELETE",
      }),
    );
  });

  it("deletes projects with DELETE", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            project_id: 7,
          }),
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.deleteProject(7)).resolves.toEqual({ project_id: 7 });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/projects/7",
      expect.objectContaining({
        method: "DELETE",
      }),
    );
  });

  it("loads the latest project analysis status", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            id: 12,
            project_id: 7,
            status: "running",
            current_step: "extract",
            progress: 42,
            message: "LLM이 원고를 분석 중입니다.",
            created_at: "2026-06-20 00:00:00",
            updated_at: "2026-06-20 00:00:01",
          }),
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.analysisStatus(7)).resolves.toMatchObject({
      status: "running",
      current_step: "extract",
      progress: 42,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/projects/7/analysis/status",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
  });

  it("cancels project analysis with POST", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            id: 13,
            project_id: 7,
            status: "cancelled",
            current_step: "cancelled",
            progress: 100,
            message: "분석이 취소되어 생성 중이던 내용이 삭제되었습니다.",
            created_at: "2026-06-20 00:00:00",
            updated_at: "2026-06-20 00:00:01",
          }),
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.cancelAnalysis(7)).resolves.toMatchObject({
      status: "cancelled",
      current_step: "cancelled",
      progress: 100,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/projects/7/analysis/cancel",
      expect.objectContaining({
        method: "POST",
      }),
    );
  });
});
