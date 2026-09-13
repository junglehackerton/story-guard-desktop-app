# 심화 검색 검사

보고서: `output/validation/embedding-advanced/index.html`

- Qwen3 Q8: Top4 30/40, Top8 33/40, 397.4초 인덱싱
- E5-small: Top4 23/40, Top8 24/40, 15.1초 인덱싱
- BGE-M3 dense: Top4 26/40, Top8 31/40, 109.9초 인덱싱
- EmbeddingGemma: Top4 29/40, Top8 31/40, 66.0초 인덱싱

앱 경로 검사 13/13. 합성 스트레스 시험이며 실제 장편 소설 및 GPT 판단 정확도는 미검증. 모델별 전체 측정값/실패 원문/검사 결과는 JSON과 HTML에 보존.

재현: build_advanced 모듈로 데이터 생성, run 모듈에 --dataset 및 --output으로 위 출력 디렉터리 지정, lifecycle 모듈 실행 후 report_advanced 모듈 실행. CPU 네 모델은 순차 실행. lifecycle은 별도 DB와 기본 GPU 설정 사용. 실제 런타임 검사는 `.venv/bin/python scripts/validation/run_structured_check.py scripts/embedding_benchmark/validate_hybrid.py --output output/validation/retrieval-strategies/fresh-runtime.json`처럼 래퍼로 실행하면 초기화 실패도 `stage`와 로그 tail을 JSON으로 보존한다.

모델 전환 경로는 `scripts/embedding_benchmark/validate_model_switch.py`로 Qwen → Gemma → Qwen 순서를 확인한다. 2026-09-11 현재 Metal 장치(`GGML_METAL_DEVICES=0`)와 Gemma 격리 Python 워커를 명시해 세 단계 검색이 모두 통과했고, Qwen 인덱스 재사용과 모델별 인덱스 분리가 확인됐다. 결과는 `output/validation/embedding-advanced/model-switch.json`에 `status: passed`, `checks: [true, true, true]`, `separate_indexes: true`, `qwen_index_reused: true`로 저장했다.

## 2026-09-11 실제 Gemma 워커 재검증

`.venv/bin/python scripts/validation/run_structured_check.py scripts/embedding_benchmark/validate_gemma_app.py --output output/validation/embedding-advanced/gemma-runtime.json`으로 현재 로컬 Gemma 격리 워커를 실행했다. EmbeddingGemma FP32 모델이 정상 초기화됐고, 152개 청크 색인에 31.95초(워커 준비 6.98초), 40개 질의에서 Top-4 정답 포함 29개를 기록했다. 이전 후보 비교의 Gemma 29/40과 일치하며 실제 앱과 같은 로컬 워커 경로가 동작한다는 추가 증거다.

같은 시점에 실행한 Qwen 앱 RAG 검사는 Metal 기본 장치를 명시하는 보정 후 통과했다. 실제 GGUF로 2개 작품·11개 청크 색인(9.853초), 프로세스 재시작 후 검색 및 삭제된 근거 제외(10.909초)를 확인했다. 이 검사는 실행·지속성 회귀군이며, 152청크·40질의 Gemma 품질군과 직접 비교하거나 장편 원고 정확도로 일반화하지 않는다. 실행 요약은 `output/validation/qwen-app-rag-current.json`에 저장했다. Chroma telemetry 호환성 경고와 llama 컨텍스트 용량 경고는 기능 결과와 분리해 기록했다.

모델 선택 UI에도 이 경계를 표시한다. Gemma 선택 시 실제 워커 측정값(152 청크 31.95초·Top-4 29/40)을 보여주고, Qwen 선택 시 합성 비교값과 실제 앱 RAG 실행·지속성 검사 결과를 구분해 안내한다. 두 모델의 장편 원고 정밀도 우열은 별도 검증 대상이다.
