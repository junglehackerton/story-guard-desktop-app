# Story Guard 1~8 인수 실행표

이 문서는 2026-09-13 현재 1~8 목표의 실행 증거와 마지막 네이티브 입력 게이트를 묶어 둔 기록이다.

## 자동·실제 provider 증거

- 새 작품 10편: `output/validation/native-new-project-20260913/REPORT.md`
- 실제 GPT 20편: `output/validation/goal-1-8-20260913/real-gpt-20.json`
- 실제 GPT 50편 증분: `output/validation/goal-1-8-20260913/real-gpt-50-incremental.json`
- 중단·취소·재개: `scripts/validation/verify_interruption_bundle.py`
- 최종 회귀: `output/validation/goal-1-8-20260913/final-regression-20260913.json`
- 브라우저 실제 백엔드 UI 흐름: `output/validation/goal-1-8-20260913/browser-ui-flow.json`
- populated 관계 그래프 UI 흐름: `output/validation/goal-1-8-20260913/populated-graph-ui.json`
- 그래프 입력 회귀: `output/validation/goal-1-8-20260913/graph-input-regression.json`
- 1~8 항목별 인수 상태: `output/validation/goal-1-8-20260913/acceptance-status.json`

## 마지막 네이티브 조작 게이트

잠금 해제된 Mac에서 최신 `src-tauri/target/release/bundle/macos/Story Guard.app`을 실행한다.

1. 관계 지도에서 `전체 관계`를 연다.
2. 트랙패드 핀치를 두 번 확대하고 두 손가락 이동으로 화면을 이동한다.
3. 노드를 선택한 뒤 관계·근거 패널이 같은 대상과 원문을 표시하는지 확인한다.
4. 창을 1440×900, 1100×720, 760×720으로 조정하고 노드가 잘리거나 페이지 전체 스크롤이 생기지 않는지 확인한다.
5. `화면에 맞춤`을 눌러 지도 전체가 복귀하는지 확인한다.

자동 회귀에서는 `trackpadZoomFactor`, `graphPanOffset`, 복잡 그래프 배치, 반응형 overflow를 검증한다. 네이티브 핀치 발생만 실제 장치 입력이 필요하다.

세부 판정·실패 기록 형식은 [네이티브 관계 지도 최종 인수 절차](2026-09-13-native-graph-gate-runbook.md)를 따른다.
