# Qwen3 공통 기능 연결 결과

2026-09-10. 범위: 전용 임베딩 준비, 원고 청킹·로컬 저장·검색, 모델 변경 시 인덱스 분리/재구성. GPT 연결과 모순 판단은 이번 구현 범위 밖이다.

## 변경

- 기본 임베딩을 Qwen3-Embedding-0.6B-Q8_0.gguf로 분리했다. 공식 GGUF revision 370f27d 다운로드 후 SHA-256을 검증하고 완성 파일로 교체한다. 기존 생성 모델 다운로드는 유지한다.
- 준비 화면과 상태 API가 임베딩과 생성 모델을 독립적으로 확인한다. 기존 로컬 분석이 아직 생성 모델에 의존하므로 전체 준비 완료는 둘 모두를 요구한다. 임베딩만 준비하는 요청은 생성 모델을 내려받지 않는다.
- LAST pooling, 질문용 Instruct/Query 접두어, 정규화, 1,024차원 유효성 검사를 적용했다. 긴 입력을 조용히 자르지 않는다. llama.cpp 호출은 잠금으로 직렬화한다.
- Chroma 컬렉션을 모델 경로/크기/수정 시각과 임베딩 설정 지문으로 구분한다. 기존 컬렉션은 자동 삭제하지 않는다. 파일 이름과 설정만 같은 다른 모델이 섞이지 않도록 파일 정보를 포함한다. 공식 다운로드는 해시 검증을 별도로 수행한다.
- SQLite의 원고 청크를 기준으로 검색 인덱스를 동기화한다. 원고 변경·삭제·회차 변경 또는 모델 변경 시 재구성하고, 원문/청크 ID/문서 ID/회차를 검색 결과에 유지한다.
- 같은 청크를 두 번 넣어도 결과가 중복되지 않도록 고정 ID로 upsert한다. 완료 표식을 원자적으로 기록하고, 실패한 동기화는 다음 검색에서 다시 시도한다.
- 백그라운드 인덱싱 오류를 로그에 남긴다.

## 실행 검증

검증 스크립트: `scripts/validate_local_rag.py`. 기존 캐시 모델을 절대 경로로 사용했으며 추가 모델 사본을 만들지 않았다. 별도 검증 데이터만 사용했다.

```sh
STORY_GUARD_GPU_LAYERS=0 .venv/bin/python -m scripts.validate_local_rag \
  --model .cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf \
  --data-dir output/validation/common-rag-new-run --stage index
STORY_GUARD_GPU_LAYERS=0 .venv/bin/python -m scripts.validate_local_rag \
  --model .cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf \
  --data-dir output/validation/common-rag-new-run --stage query
```

매번 새 검증 디렉터리를 지정한다. query 단계는 예외 문서를 삭제하는 검사까지 포함하므로 같은 디렉터리에서 반복 실행하는 용도가 아니다. macOS의 해당 런타임은 CPU 레이어 설정이어도 Metal 초기화를 시도하므로 장치 접근이 필요했다.

실행 결과 (`output/validation/common-rag-run1`):

- 두 작품, 한국어 합성 원고 11청크. 실제 파서 → SQLite → Qwen3 → Chroma 저장 성공. 약 6.84초.
- 별도 Python 프로세스로 재시작 후 규칙·계약 거절·검 사용 근거 검색 성공. 각 결과의 청크 ID로 SQLite 원문 일치 확인.
- 계약 성립 장면이 있는 작품에서만 해당 장면이 검색됨. 해당 문서를 삭제하면 검색에서 사라짐. 검색 및 삭제 검증 전체 약 7.97초.
- 전체 backend pytest: 79 passed. frontend: 25 passed. TypeScript/Vite build 성공. git diff --check 성공.

## 남은 검증과 한계

- 합성 짧은 원고의 검색 검사이며 일반적인 검색 정확도나 GPT 모순 판단 정확도를 뜻하지 않는다.
- UI 클릭 흐름, 패키징 앱, Windows, 장편 원고의 속도·메모리는 미검증이다.
- 원고 변경 시 해당 작품 전체를 다시 임베딩하는 보수적인 구현이다. 긴 원고에서는 변경 청크만 재계산하도록 개선할 여지가 있다.
- 현재 분석기는 로컬 생성 모델로 후보를 만든 뒤 RAG 근거를 보강한다. 검색된 근거를 사용자 GPT에 먼저 보내 판단시키는 흐름은 아직 구현하지 않았다.
- 현재 UI에는 청크별 인덱싱 진행/실패 표시가 없다. 로그로 원인을 확인할 수 있지만 사용자에게 직접 재시도 상태를 보여주는 후속 작업이 필요하다.
- 의존성 경고: OpenTelemetry deprecation 및 Chroma/PostHog 호환 로그, Vite 500kB 초과 번들 경고가 있었다. 테스트와 검증은 통과했으며 의존성 업데이트는 하지 않았다.
- 사용자 데이터와 기존 디자인/발표 자료는 보존했다. 커밋·푸시는 수행하지 않았다.
