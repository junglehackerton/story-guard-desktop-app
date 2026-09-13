# 로컬 임베딩 모델 비교

상세 HTML: `output/validation/embedding-comparison/index.html`

| 모델 | 근거 전부 Top4 | MRR | 임베딩(168구간) | 검색 중앙값 | 최대 RSS |
|---|---:|---:|---:|---:|---:|
| Qwen3-Embedding-0.6B Q8 | 40/40 | 0.829 | 93.60초 | 1490.8ms | 2213MiB |
| multilingual-e5-small | 38/40 | 0.812 | 3.43초 | 20.2ms | 930MiB |
| BGE-M3 (dense) | 38/40 | 0.827 | 29.60초 | 167.9ms | 2004MiB |
| EmbeddingGemma-300m | 39/40 | 0.809 | 17.26초 | 95.5ms | 1371MiB |

EmbeddingGemma는 사용자 이용 조건 동의 및 로컬 계정 인증 후 실제 측정을 완료했다.

CPU 4스레드, Qwen Q8 GGUF/llama.cpp와 E5·BGE·EmbeddingGemma FP32/PyTorch 실행 조합 비교다. GPU 성능·순수 아키텍처 우열·장편 소설 분석 정확도를 주장하지 않는다. BGE는 dense만 사용했다.

합성 짧은 구간 168개(120개 반복 방해 구간), 질문 40개, 단일 실행이다. 작은 자체 제작 시험이므로 결과를 일반화할 수 없다.

평가 데이터는 모델 결과 확인 전 생성하고 SHA256으로 고정했다. 각 JSON에 문항별 검색 순위, 입력 최대 토큰 수, 실제 실행 시간, 메모리와 실행환경이 있다. 입력을 잘라내지 않았다.

E5는 query:/passage: 접두사와 masked mean pooling, BGE는 접두사 없이 CLS pooling, Qwen은 현재 앱 지시문과 last-token pooling을 사용했다. EmbeddingGemma는 공식 query/document 접두사, mean pooling, 두 Dense 층, 정규화 및 768차원을 사용했다.

기본 모델은 아직 교체하지 않았다. Qwen은 이번 시험의 근거 완전 검색률이 가장 높고, E5는 CPU 속도가 가장 빠르다. EmbeddingGemma는 39/40과 약 96ms로 후속 비교 후보지만 원본 모델 용량이 약 1.2GiB다. 놓친 규칙을 보완하는 검색 전략과 독립 장편 원고 평가가 선행되어야 한다.

재현: 각 모델을 별도 프로세스로 순차 실행한다. Qwen은 `.venv/bin/python -m scripts.embedding_benchmark.run qwen`, E5/BGE는 `.cache/embedding-bench-venv/bin/python -m scripts.embedding_benchmark.run e5` 또는 `bge`, `gemma`. 보고서: `.venv/bin/python scripts/embedding_benchmark/report.py`. 모델 다운로드 revision은 `.cache/embedding-bench-models/manifest.json`, 런타임 패키지는 `output/validation/embedding-comparison/runtime-lock.txt`, Gemma 추가 환경은 `runtime-lock-gemma.txt`에 기록했다.
