# 정적 웹 데모 미리보기

팀원이 서버나 Python 환경을 설치하지 않고 공개 샘플 흐름을 확인할 때 사용하는 빌드입니다.

## 만들기

```bash
npm install
npm run build:demo:static
python3 scripts/make-static-demo-html.py
```

생성된 `demo-static.html`은 CSS·JS·로고·미리보기 이미지를 하나로 묶은 파일입니다. 파일을 브라우저에서 직접 열거나 그대로 공유할 수 있습니다. `demo-dist/index.html`과 `demo-dist/assets/`는 폴더 형태로 공유할 때 사용합니다. 별도 프론트 서버·백엔드·API 키가 필요하지 않습니다.

## 정적 모드의 범위

- 소개 페이지, 튜토리얼, 공개 샘플 원문, 검토 결과, 관계 지도, 떡밥 후보를 탐색할 수 있습니다.
- 작가 판단과 화면 내 상태는 브라우저에만 저장됩니다.
- `새 문장으로 실시간 분석` 화면은 서버 요청을 만들지 않고 정적 미리보기 안내를 표시합니다.
- GPT API 키, Qwen 모델, 임베딩 서버, 사용량 DB는 포함되지 않습니다.

실제 심사용 배포는 `npm run build:demo`와 `backend.app.demo_server:app`을 사용해야 하며, API 키 설정·Qwen 사전 색인·동시성 제한이 필요합니다. 자세한 내용은 [`web-demo-deployment.md`](web-demo-deployment.md)를 참고하세요.
