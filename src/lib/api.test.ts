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

    await expect(api.health()).resolves.toEqual({ status: "ok" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/health",
      expect.objectContaining({
        headers: expect.objectContaining({
          "Content-Type": "application/json",
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
});
