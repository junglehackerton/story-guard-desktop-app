import { ApiRequestError } from "./api";

export function friendlyStartupError(error: unknown): string {
  if (error instanceof ApiRequestError) {
    const action = error.kind === 'http' && (error.status === 401 || error.status === 403)
      ? '로컬 API 인증을 확인하지 못했습니다. 앱을 다시 실행해 주세요.'
      : '요청을 다시 시도할 수 있습니다.';
    return `${error.message} ${action} (요청: ${error.method} ${error.path} · ${error.attempts}회 시도${error.status ? ` · HTTP ${error.status}` : ''})`;
  }
  const message = error instanceof Error ? error.message : String(error ?? "");

  if (/failed to fetch|networkerror|load failed/i.test(message)) {
    return "로컬 작업실에 연결하지 못했습니다. 아래 ‘다시 확인’으로 재시도해 주세요.";
  }

  if (message.includes("인증 토큰")) {
    return "로컬 API 인증이 만료되었습니다. 앱을 완전히 종료한 뒤 다시 실행해 주세요.";
  }

  if (!message.trim()) {
    return "로컬 작업실을 준비하지 못했습니다. 다시 확인해 주세요.";
  }

  return message;
}
