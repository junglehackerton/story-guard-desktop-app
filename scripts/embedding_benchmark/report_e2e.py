from pathlib import Path
import json,html
root=Path(__file__).resolve().parents[2];out=root/'output/validation/model-e2e';r=json.loads((out/'results.json').read_text());settings=json.loads((out/'app-settings.json').read_text())
assert r['requests']<=8
labels={'conflict':'명백한 계약 위반 탐지','cached_decision':'보류 판단 유지·캐시 재사용','revised_exception':'계약 체결로 수정 후 충돌 해소'}
rows=[]
for c in r['cases']:
 for s in c['stages']:
  rows.append(f"<tr><th>{c['embedding']}</th><td>{labels[s['stage']]}</td><td>{'통과' if s['passed'] else '실패'}</td><td>{s['seconds']:.1f}초</td><td>{s['requests']}회</td><td>{html.escape(s.get('error',''))}</td></tr>")
body=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Story Guard GPT 통합 검증</title><style>body{{font:16px/1.7 system-ui;background:#F7F5EF;color:#252A27;margin:0}}main{{max-width:1100px;margin:auto;padding:40px 24px}}section{{background:#FFFDF8;padding:24px;border:1px solid #DADFD8;border-radius:8px;margin:20px 0}}table{{border-collapse:collapse;width:100%}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #DADFD8}}th,a{{color:#24635B}}</style><main><a href="../retrieval-strategies/index.html">← 검색 방식 비교</a><h1>실제 GPT 연결로 두 모델의 전체 분석 경로 확인</h1><p>GPT: {r['model']} · 추론 low · 실제 요청 {r['requests']}/8회 · 합성 원고만 전송</p><section><table><tr><th>임베딩</th><th>검사</th><th>결과</th><th>소요 시간</th><th>새 GPT 요청</th><th>오류</th></tr>{''.join(rows)}</table></section><section><h2>앱 연결</h2><p>실행 중인 백엔드를 동일 데이터와 포트로 최신 코드에 맞춰 재시작했다. 앱 설정 API에서 두 모델 저장과 설치 준비 상태를 확인했고, 기존 Qwen 선택은 복원했다. Gemma 파일은 이미 다운로드한 원본을 연결해 재다운로드하지 않았다.</p><h2>확인 범위</h2><p>실제 RagService·SQLite·Chroma·GPT 분석 서비스와 사용자 GPT 계정을 사용했다. 충돌 원고를 분석하고 보류한 뒤 같은 원고 재분석에서 캐시·판단 유지를 확인했다. 계약이 성립한 내용으로 수정한 후 과거 청크를 제거하고 충돌이 사라지는지 확인했다.</p><p>두 청크가 검색 범위에 모두 들어가는 작은 사례이므로 모델 검색 품질의 우열을 평가하지 않는다. GPT 응답 변동과 초기 모델 로딩이 포함된 시간이므로 임베딩 속도 비교에도 쓰지 않는다. 작가의 장편 원고, 설치부터 UI 업로드까지의 전체 조작 시간, Windows 설치판은 미검증이다.</p><p>원고 문장은 사용자 작품이 아닌 가상의 계약·봉인검 사례다. 기존 작품 데이터는 수정하지 않았다. 세부 근거와 요청 수는 results.json에 보존한다.</p></section></main></html>'''
(out/'index.html').write_text(body)
(root/'docs/model-e2e-validation.md').write_text('# 두 임베딩 모델 실제 GPT 통합 검증\n\n보고서: `output/validation/model-e2e/index.html`\n\n'+ '\n'.join(f"- {c['embedding']}: "+', '.join(f"{s['stage']}={s['passed']}" for s in c['stages']) for c in r['cases'])+f"\n\n요청 {r['requests']}/8. 소규모 합성 원고이므로 모델 우열·장편 분석 정확도·UI 업로드 시간을 주장하지 않는다.\n")
print('Report generated',sum(s['passed'] for c in r['cases'] for s in c['stages']))
