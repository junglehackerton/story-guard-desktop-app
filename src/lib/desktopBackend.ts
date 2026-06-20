import { invoke } from "@tauri-apps/api/core";
import { Command, type Child } from "@tauri-apps/plugin-shell";
import { api, setApiToken } from "./api";

let backendProcess: Child | null = null;
let startPromise: Promise<string> | null = null;
const BACKEND_READY_TIMEOUT_MS = 60_000;
const BACKEND_READY_INTERVAL_MS = 250;

export function isTauriRuntime() {
  return "__TAURI_INTERNALS__" in window;
}

export async function ensureDesktopBackend(): Promise<string> {
  if (!isTauriRuntime()) {
    return "웹 개발 모드: 외부 backend 서버를 사용합니다.";
  }
  const token = await invoke<string>("api_token");
  setApiToken(token);
  if (backendProcess) {
    await waitForBackendReady();
    return "데스크톱 backend sidecar 실행 중";
  }
  if (startPromise) {
    return startPromise;
  }

  startPromise = startSidecar(token).catch((error) => {
    startPromise = null;
    throw error;
  });
  return startPromise;
}

async function startSidecar(token: string): Promise<string> {
  const appDataDir = await invoke<string>("app_data_dir");
  const command = Command.sidecar("binaries/story-guard-backend", [], {
    env: {
      STORY_GUARD_DATA_DIR: appDataDir,
      STORY_GUARD_BACKEND_PORT: "8765",
      STORY_GUARD_API_TOKEN: token,
    },
  });
  command.stdout.on("data", (line) => console.info(`[story-guard-backend] ${line}`));
  command.stderr.on("data", (line) => console.warn(`[story-guard-backend] ${line}`));
  command.on("close", () => {
    backendProcess = null;
    startPromise = null;
  });
  backendProcess = await command.spawn();
  await waitForBackendReady();
  return `데스크톱 backend sidecar 시작: pid ${backendProcess.pid}`;
}

export async function waitForBackendReady(
  timeoutMs = BACKEND_READY_TIMEOUT_MS,
  intervalMs = BACKEND_READY_INTERVAL_MS,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown = null;
  while (Date.now() < deadline) {
    try {
      await api.health();
      return;
    } catch (error) {
      lastError = error;
      await delay(intervalMs);
    }
  }
  const message = lastError instanceof Error ? lastError.message : "응답 없음";
  throw new Error(`데스크톱 backend가 시작되지 않았습니다. 마지막 오류: ${message}`);
}

function delay(ms: number) {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms));
}
