# 웹 데모 로컬 검증 — 2026-09-15

## 확인한 결과

- 기존 데스크톱 원고·검토·관계 지도 컴포넌트를 웹 빌드에서 공유.
- 백로호텔 공개 원고 10화, 근거 청크 123개, 엔티티 138개, 관계 205개, 검토 후보 3개를 읽기 전용 DB에서 추출.
- 샘플 파일과 DB 원문 일치, 검토 근거 존재, 인용문 본문 포함 여부, 개인 경로/토큰 미포함 검사 통과.
- 브라우저에서 녹색 열쇠 후보 선택 → 3화 원문 하이라이트 → 관계 지도 내 관련 7개 관계 → 검토 복귀 확인.
- 판단 보류 후 확인 대기 2개/작가 판단 1개로 변경, 새로고침 후 유지, 초기화 후 3개/0개 복원 확인.
- 관계 지도 캔버스 실제 렌더링 확인.
- 390×844에서 데모 반응형 확인. 문서 폭 390px로 가로 넘침 없음. 검증 후 기본 뷰포트 복원.

## 임베딩 실측

기존 Qwen3-Embedding-0.6B-Q8_0.gguf로 공개 샘플 369구간을 실제 계산. `output/web-demo/index.npz`에 저장. 원문 앞뒤 문맥을 확장하여 근거를 반환.

| 질의 | 회차 제한 | 검색 시간 | 확인 |
| --- | --- | --- | --- |
| 온전한 녹색 황동 열쇠로 사물함을 여는 문장 | 1~3화 | 0.67초 | 3화 열쇠 절단 근거 포함 |
| 서우가 스물다섯 살이라는 문장 | 1화 | 0.36초 | 열아홉 살이라는 대화 근거 포함 |

이 Mac에서 모델이 준비된 상태의 2개 검색 실측이며, 배포 서버 속도나 전체 분석 정확도를 보장하지 않습니다. GPT 응답 시간은 포함하지 않습니다.

## 자동 검증

- 프런트: 25개 파일, 126개 테스트 통과.
- 백엔드: 239개 테스트 통과. 기존 의존성 deprecation 경고 1개.
- 공개 API 테스트: 하루 한도, 날짜 변경, 중복 요청, 4명 동시 실행, 5번째 슬롯 거절, 예산, 미설정 키, 입력 범위/버전, 잘못된 근거 거부, 실패 비용 예약/환불, 비공개 라우트 미노출.
- API 테스트의 GPT/검색 응답은 테스트 대역이며 유료 호출하지 않음. 실제 Qwen 검색은 위 별도 실측으로 확인.
- 웹 데모 및 데스크톱 프런트 빌드 통과. Vite의 큰 청크 경고는 남아 있음.
- `git diff --check` 통과.

## 미검증 / 운영 전 필요

- GPT 실제 API 응답: 서버 API 키 미설정. 개인 구독을 공용 처리 서버로 연결하지 않음.
- 실제 공개 호스팅, HTTPS 프록시/IP 전달, 배포 CPU·메모리 부하, 외부 접속 및 가동 시간 모니터.
- 요금·환율 설정과 영속 사용량 볼륨. 80% 경고는 서버 로그만 제공.
- 네이티브 Tauri 장치 실행을 다시 하지 않음. 프런트 회귀 테스트와 빌드만 검증.

## 후속 수정 — 스크롤 및 독립 실행

- 원인: 데스크톱 `.page-graph .workspace`의 `overflow:hidden`이 데모에도 적용됨. 데스크톱은 자식 `.graph-page`가 스크롤하지만 데모는 `.page-content`를 사용하므로 휠 입력이 막힘.
- 수정: 701px 이상 데모 관계 지도에서만 본문의 세로 스크롤을 활성화. 모바일 및 데스크톱 앱 CSS 동작은 유지.
- 브라우저 실측: 같은 윤해주 중심 상태에서 `scrollTop` 0 → 1882 → 919 왕복. 관계 20개를 모두 펼친 뒤 2885(맨 아래) → 0(맨 위) 이동 확인.
- 독립 배포 묶음 `output/web-demo-release-20260915` 생성. 허용 목록 기반 18개 파일, 해시 검사 통과. 개인 DB/인증/사용량 기록 제외.
- `scripts/verify-web-demo-package.py` 통과: 빈 별도 작업 폴더에서 원본 데스크톱 DB 없이 10화/205관계 표시, 묶음 안 Qwen 모델로 열쇠 절단 근거 검색 성공.
- 사용량 파일을 유지한 새 프로세스에서 남은 검토 2회 유지 확인. 이는 로컬 영속 파일 검증이며 실제 호스팅 볼륨/백업 설정 완료를 뜻하지 않음.

## 2026-09-15: guided first-use flow

- Entry is now the saved, actual key continuity candidate (issue 70): chapter 3 destruction vs chapter 5 reappearance/use. Verbatim excerpts link to focused source highlights and back to the guide.
- Guide judgments share the existing review storage and counts; clue statuses have separate versioned browser storage. A blocked browser store permits session-only decisions with an explicit notice.
- Related graph handoff starts at the key and collapses repeated analysis/evidence. Full evidence remains available.
- Clue chapter links are derived from saved mention/relation evidence. They are labelled evidence chapters, not an exhaustive appearance history; missing evidence is explicitly shown.
- First entry does not request AI status. Live analysis is labelled separately and initialized when the analysis screen opens. Input/results remain mounted across source navigation. GPT remains unconfigured here; actual live inference is not claimed as tested.
- `build:demo` now runs the curated-source tests before bundling. Stale source quotations or the wrong chapters fail the release build; runtime also falls back to the regular review when curated evidence is unavailable.

### Verification performed

- Frontend suite: 131 tests passed; subsequent targeted demo suite: 8 passed. Desktop and demo production builds passed (existing large-chunk warning remains).
- Real browser: 3화 source navigation/highlight/return; judgment change; reload persistence; review counts 2 open / 1 judged; clue state persistence; reset; unconfigured AI messaging and saved-result navigation.
- Separate `localhost` origin: initial unjudged sample available independently of the existing `127.0.0.1` browser state. Mobile 390×844: readable stacked quotations, working judgment buttons, no horizontal overflow (document width 390).
- Live analysis state is component-memory-only; the analysis request is aborted when the demo analysis view unmounts, so a result is not restored or shown to a later visitor.
- Browser E2E follow-up: entered the example sentence, moved to 검토 결과, returned to 분석, and confirmed the textbox was reset to `0 / 1,200자`; the unconfigured GPT action remained disabled and no private result was shown.
- Graph wheel scrolling verified at scrollTop 963 with scrollHeight 2604, then returned upward.
- Portable release: `output/web-demo-release-guided-20260915`; 18 hashes verified. Isolated process loaded 10 chapters / 205 relations, served static root, searched the bundled embeddings, and retained usage (remaining 2) across process restart without the original desktop database/model path.
- Captures: `output/validation/demo-guided-flow/desktop-entry.png`, `mobile-entry.png`, `graph.png`.

### 동시 요청 정책 검증 — 2026-09-16

- 서로 다른 쿠키 방문자 4명이 서로 다른 문장을 동시에 제출했을 때 네 요청 모두 `200`과 각자의 `remaining: 2`를 반환.
- 분석 중 슬롯을 모두 점유한 상태에서 5번째 요청은 `429`를 반환하고 사용량 DB에 예약 행을 만들지 않음.
- Qwen 검색은 공유 임베더 잠금 안에서 짧게 실행하고, GPT 호출은 잠금 밖에서 병렬 처리. 단일 Uvicorn 프로세스 기준으로 검증함.

### 실제 로컬 AI E2E — 2026-09-16

- 데스크톱 앱에 저장된 ChatGPT 계정 세션(`ChatGptConnection`, Codex transport)을 로컬 전용 어댑터로 연결하고, 데모 서버에는 `STORY_GUARD_DEMO_OPENAI_BASE_URL`로만 주입했습니다. 공개 배포 경로는 계속 API 키 방식입니다.
- 인앱 브라우저에서 새 문장을 입력하고 실제 Qwen 검색 → 데스크톱 ChatGPT 구독 모델(`gpt-5.6-luna`) → 근거 ID 검증 → 결과 표시까지 완료했습니다. 화면에는 충돌 후보, 실제 원문 근거 3개, 남은 검토 2회가 표시되었습니다.
- 결과가 표시된 뒤 검토 결과 화면으로 이동했다가 분석 화면으로 돌아와 입력과 실시간 결과가 `0 / 1,200자` 및 미표시 상태로 초기화되는 것을 확인했습니다.
- 로컬 구독 E2E의 전체 요청은 브라우저에서 약 30초 안에 완료되었습니다(대부분은 ChatGPT 응답 대기). Qwen 검색 자체는 앞선 실측처럼 약 0.36~0.67초 범위입니다.
- 실시간 문장 결과는 현재 분석 화면의 임시 결과로만 표시됩니다. 기존 검토 후보 3개와 관계 205개를 자동 수정하거나 저장하지 않으며, 화면을 나가면 사라집니다. 이는 한 방문자의 입력이 공개 샘플을 오염시키지 않도록 한 정책입니다.
- 이 테스트는 로컬 구독 세션을 사용한 실제 1건 E2E입니다. 실제 공개 호스팅, 4개 브라우저의 실 GPT 동시 부하는 아직 별도 검증 대상입니다.

### Not yet verified

External first-time-user comprehension, real GPT response behavior through the public web, public deployment/uptime, and full keyboard/screen-reader accessibility. The proposed 3-minute usability criterion remains a user-test target, not a measured outcome.

### 2026-09-16: 근거 수정 후 재분석 E2E

- 첫 방문 화면에 서비스 소개와 체험 순서를 추가하고, `3분 체험 시작하기` CTA에서 기존 guided demo로 진입하는 브라우저 흐름을 확인했습니다.

- 인앱 브라우저에서 동일한 황동 열쇠 문장을 분석해 `충돌 후보`와 Qwen 검색 근거를 표시했습니다.
- 표시된 기존 근거의 textarea에서 “절단한 열쇠를 버린 뒤 다른 예비 열쇠로 교체”로 수정하고 `수정한 근거로 다시 검토`를 실행했습니다.
- 두 번째 응답은 `뚜렷한 충돌 없음`과 `수정안으로 해결 확인`을 표시했고, 검토 화면의 임시 배너가 `이전 후보가 해소됨`으로 바뀌었습니다. 관계 지도는 새 문장 노드를 만들지 않고 기존 윤해주 관계를 유지했습니다.
- 수정 원문은 해당 브라우저 요청에만 전달되며 snapshot, 임베딩 인덱스, 사용량 DB 본문에는 저장되지 않습니다. 최초 시도에서는 ChatGPT 스트림이 일시적으로 502였지만 재시작 후 실제 데스크톱 ChatGPT 구독 모델 응답으로 같은 반복 검증을 완료했습니다. 응답은 `clear`였고, “수정본을 현재 설정으로 인정하면 충돌은 해소된다”고 설명했습니다.
