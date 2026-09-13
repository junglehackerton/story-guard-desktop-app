# 검색 개선 검증

HTML: `output/validation/retrieval-strategies/index.html`

Qwen 30/40 → 35/40, 회귀 0. 새 합성 사례 12/12 → 12/12. 실제 작가 원고 및 GPT 최종 판단은 미검증.

GPT 분석에서 strategy=hybrid를 명시하여 벡터 2개+문단 BM25 2개를 결합한다. 나머지 호출의 기본값 dense는 유지한다. API 비용 및 모델 추가 없음. 동일 개수이며 토큰 수 동일 보장은 아님.

실험 알고리즘과 제품 함수의 결과가 네 모델·160질의에서 일치함을 report_strategies로 확인했다.
