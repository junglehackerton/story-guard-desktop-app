# ChatGPT 기기 코드 연결 구현

2026-09-10. 공식 근거: https://learn.chatgpt.com/docs/app-server#3b-log-in-with-chatgpt-device-code-flow

## 범위

- Codex app-server stdio JSON-RPC 연결. 초기화, 요청 ID 매칭, 시간 제한, 프로세스 종료 처리.
- ChatGPT 기기 코드 로그인, 인증 대기/실패/만료, 취소, 로그아웃.
- 공식 OpenAI 인증 주소만 브라우저로 열기. 사용자가 직접 인증한다.
- 계정이 chatgpt 모드인지 확인하고 서버가 반환한 모델 목록만 선택 가능.
- 명시적 버튼으로 가상 원고 4문장의 분석 응답 확인. 기존 작품 원고는 이 기능에서 전송하지 않는다.
- 기존 로컬 분석 파이프라인은 유지한다. RAG 근거를 GPT에 보내는 실제 작품 분석은 후속 작업이다.

## 인증 저장소와 실행 파일

`STORY_GUARD_DATA_DIR/chatgpt-auth`에 app-server 전용 인증 데이터를 저장한다. 일반 데이터 폴더 미설정 시 `~/.story-guard/chatgpt-auth`이다. 기존 `~/.codex`를 복사하거나 읽지 않는다. 하위 프로세스에는 OPENAI_API_KEY, CODEX_ACCESS_TOKEN 등 상위 프로세스의 인증 환경변수를 전달하지 않는다. 파일 저장 방식을 지정하여 다른 앱의 Keychain 자격증명과 공유하지 않는다. 이 폴더는 민감한 인증 데이터이므로 공유/커밋 대상이 아니다.

실행 파일 선택: `STORY_GUARD_CODEX_BIN` 명시 경로 → Mac ChatGPT/Codex 앱 내부 실행 파일 → PATH. 이번 환경의 PATH Codex 0.36.0은 app-server 미지원, ChatGPT 앱 내 0.153.4는 지원했다. 개발에서는 후자를 사용했다. Mac·Windows 배포용 런타임 동봉/설치·업데이트 및 라이선스 검토는 아직 하지 않았다. 모든 사용자에게 이미 실행 파일이 있다고 가정하면 안 된다.

## 개발 실행

```sh
STORY_GUARD_DATA_DIR="$PWD/.cache/chatgpt-integration" \
STORY_GUARD_CODEX_BIN=/Applications/ChatGPT.app/Contents/Resources/codex \
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 18765
VITE_STORY_GUARD_API=http://127.0.0.1:18765 npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

이 경로는 기존 작품과 분리한 개발 데이터다. 실제 인증 코드와 토큰은 문서/테스트 결과에 보관하지 않는다. 코드가 만료되면 화면에서 다시 연결한다. 테스트는 `npm test`, 격리된 STORY_GUARD_DATA_DIR를 지정한 `python -m pytest backend/tests -q`로 실행한다.

## 검증 상태

- 실제 app-server 초기화 성공.
- 실제 OpenAI 기기 코드 발급 성공.
- React 화면에서 기기 코드/인증 페이지 버튼/대기 상태 표시 확인.
- 사용자 인증 완료, 인증 후 실제 모델 목록, 실제 GPT 응답은 사용자 인증 후 확인해야 한다. 자동 테스트의 가짜 응답을 실제 GPT 응답으로 취급하지 않는다.
- 브라우저 개발 화면을 확인했으며 Tauri 패키징·Windows는 미검증.
- 기존 로컬 분석 화면과 새 연결 영역을 구분하여 표시한다.
- 샘플 분석은 90초 제한, 읽기 전용 샌드박스, 별도 빈 작업 폴더, 도구 사용 금지 지시로 실행한다. API 키 과금으로 전환하지 않는다.
- 기존 번들 크기/OpenTelemetry 경고는 남아 있다.

## 후속 작업

로그인 성공 후 사용 가능한 모델로 샘플 응답을 실제 확인한다. 그다음 로컬 검색 근거를 전달하는 작품 분석 연결, 사용 한도/모델 설정 지속 저장, 인증 작업 중 프로세스 재시작/네트워크 복구, Mac·Windows 배포 런타임을 검증한다.

## 추론 강도 선택 추가

사용자 인증 완료 후 실제 계정 연결 상태와 모델 목록 조회를 확인했다. `supportedReasoningEfforts`, `defaultReasoningEffort`를 UI에 전달하여 모델별 지원 단계만 선택하도록 했다. Low/Medium/High 및 지원 모델의 XHigh/Max/Ultra 등을 표시한다. 모델 전환 시 새 모델의 기본값으로 변경하고, 서버에서 선택한 모델과 강도 조합을 검증한다. 샘플 요청의 `turn/start.effort`에 값을 전달한다.

실제 브라우저에서 GPT-6-Astra의 Medium 기본값과 GPT-5.6-Sol 전환 시 Low 기본값을 확인했다. 호출 파라미터 전달 및 지원하지 않는 값 거절을 자동 테스트했다. 이번 추가 작업에서 실제 모델 응답을 새로 요청하지는 않았다. 전체 backend 89 tests, frontend 30 tests 통과, build 및 diff check 통과.
