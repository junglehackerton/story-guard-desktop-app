# 로컬 임베딩 실행 및 프로젝트 용량 점검

검증일: 2026-09-10. 앱 소스와 기존 파일은 수정하거나 삭제하지 않았다.

## 실제 모델 실행

- 모델: Qwen/Qwen3-Embedding-0.6B-GGUF, Q8_0, revision 370f27d.
- 공식 출처: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF
- 파일: `.cache/model-validation/Qwen3-Embedding-0.6B-Q8_0.gguf`, 639,150,592 bytes. Git 제외 경로.
- 환경: 현재 프로젝트 Python 환경, llama-cpp-python 0.3.31, Mac arm64, CPU 4 threads, n_gpu_layers=0, context 2048, LAST pooling.
- 실행 스크립트: `output/validation/qwen_embedding_smoke.py`
- 원시 결과: `output/validation/qwen-embedding-smoke.json`
- 최초 샌드박스 실행은 Metal command queue 생성 실패. 장치 접근이 가능한 실행 환경에서 동일 스크립트 성공. CPU 레이어 설정이어도 이 런타임은 Metal 초기화를 시도했다.

한국어 합성 문단 8개를 1,024차원 정규화 벡터로 생성했다. 로드 11.35초, 문단 임베딩 총 2.778초. 질문 임베딩은 0.4045~0.5452초였다. 질문에는 Qwen 권장 형태인 Instruct/Query 지시문을 사용했다.

질문 5개 중 기대 근거가 1위인 경우 4개, 상위 3개 내에 든 경우 5개였다. 편지 발신자 질문에서는 편지 발견 장면이 1위, 발신자 공개 장면이 2위였다. 이는 여러 근거를 검색해 후속 분석에 전달할 필요를 보여준다. 작은 합성 데이터의 실행 확인이며 일반 정확도 수치로 해석할 수 없다.

Chroma 저장·검색, 앱 UI, 긴 원고, GPT 연결·판단, Windows 실행은 이번 검사에 포함하지 않았다. 결과의 peak RSS는 모델 파일 해시 계산 등 테스트 프로세스 전체의 최고값이므로 모델 단독 메모리 요구량으로 해석하지 않는다.

## 현재 공통 코드와 차이

`backend/app/services/local_ai.py`의 기본 임베딩 모델은 아직 Qwen2.5-1.5B-Instruct 생성 모델과 동일하다. 이번 검증은 별도 스크립트이며 앱 기본 모델을 교체하지 않았다. 실제 통합 시 전용 모델 다운로드·경로, 질문 지시문, pooling, 인덱스 재생성과 기존 데이터 호환성을 함께 검증해야 한다.

## 용량

모델 다운로드 전 프로젝트 총 약 4.1G, 다운로드 후 약 4.7G. 아래는 du 측정치이며 반올림 및 파일시스템 할당량이 포함된다.

| 경로 | 용량 | 용도 |
|---|---:|---|
| src-tauri/target | 2.5G | Rust debug/release 빌드 산출물 |
| .venv | 529M | Python 실행 환경과 라이브러리 |
| .rustup | 528M | 로컬 Rust 도구 모음 |
| .cargo | 178M | Rust 의존성 캐시와 도구 |
| node_modules | 148M | 프런트엔드 개발 의존성 |
| .git | 125M | Git 저장소 데이터 |
| docs | 58M | 발표 HTML, 디자인 이미지 등 |
| build | 34M | 패키징 빌드 작업 파일 |
| output | 25M | 검증 및 시각 자료 산출물, 이번 검사 전 기준 |

큰 항목 중 target은 재빌드할 수 있는 산출물이다. 개발 환경 폴더는 지우면 재설치가 필요하다. .git은 삭제 대상으로 판단하지 않았다. docs에는 공유용 HTML에 내장된 이미지와 별도 디자인 이미지가 포함된다. 기존 파일은 모두 보존했다. 다운로드한 모델은 약 639MB이며 du 할당량은 624M이다.
