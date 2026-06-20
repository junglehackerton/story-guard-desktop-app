import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import { waitForBackendReady } from "./desktopBackend";

describe("desktop backend readiness", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("retries health checks until the sidecar is ready", async () => {
    vi.useFakeTimers();
    const healthMock = vi
      .spyOn(api, "health")
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockResolvedValueOnce({ status: "ok" });

    const ready = waitForBackendReady(1_000, 25);
    await vi.advanceTimersByTimeAsync(25);

    await expect(ready).resolves.toBeUndefined();
    expect(healthMock).toHaveBeenCalledTimes(2);
  });

  it("reports a clear timeout when the sidecar never becomes ready", async () => {
    vi.useFakeTimers();
    vi.spyOn(api, "health").mockRejectedValue(new Error("connection refused"));

    const ready = waitForBackendReady(50, 25);
    const expectation = expect(ready).rejects.toThrow("데스크톱 backend가 시작되지 않았습니다");
    await vi.advanceTimersByTimeAsync(75);

    await expectation;
  });
});
