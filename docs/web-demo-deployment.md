# Story Guard 웹 데모 배포

웹 데모는 별도 빌드(`npm run build:demo`)의 `demo-dist` 폴더에서 동작합니다. 데스크톱 작업실(`/`)과 분리되어 브라우저에서 임베딩 모델을 내려받거나 실행하지 않습니다.

정적 호스팅에는 `demo-dist` 전체를 업로드합니다. GPT API 서버가 다른 도메인에 있으면 빌드 전에 `VITE_DEMO_API_URL=https://api.example.com`을 설정합니다.

## 동작 범위

- `src/demoData.ts`의 백로호텔 샘플은 미리 준비한 검색·관계 결과를 즉시 보여줍니다.
- 원고, 관계 지도, 검토 결과, 떡밥 후보 탭은 추가 분석 없이 탐색할 수 있습니다.
- `POST /api/demo/analyze`만 GPT를 호출합니다.
- 방문자 쿠키와 서버 메모리 집합으로 한 브라우저당 1회 사용을 제한합니다.

## 서버 환경 변수

배포 서버에 다음 값을 설정합니다.

```text
STORY_GUARD_DEMO_OPENAI_API_KEY=...
STORY_GUARD_DEMO_MODEL=gpt-4o-mini
```

API 키가 없을 때는 가짜 결과를 반환하지 않고 503 메시지를 표시합니다. 실제 운영에서는 서버 인스턴스가 여러 개일 수 있으므로, 1회 제한을 Redis 또는 영속 세션 저장소로 옮겨야 합니다.

## 사전 색인 데이터 교체

실제 데모 원고와 임베딩 결과를 교체할 때는 `src/demoData.ts`의 표시용 데이터와 `backend/app/main.py`의 GPT 근거 문맥을 같은 버전으로 갱신합니다. 웹 요청 경로에서는 `RagService.sync_project`나 임베딩 모델을 호출하지 않습니다.
