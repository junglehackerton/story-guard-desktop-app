export const DEMO_DATA = {
  title: "백로호텔의 마지막 손님",
  subtitle: "원고를 읽는 동안 생기는 연결의 빈틈을 한눈에 발견하세요.",
  chapters: ["문을 여는 사람", "두 번 울리는 전화", "잠긴 객실", "기록 테이프"],
  excerpt: "문을 열기 전에 반드시 두 번 두드릴 것.\n\n윤해주는 철거 직전의 호텔 정문을 두 번 두드렸다. 유리 너머로 먼지만 움직였다.",
  entities: [
    { name: "윤해주", type: "인물", tone: "teal" },
    { name: "민규백", type: "인물", tone: "teal" },
    { name: "서우", type: "인물", tone: "teal" },
    { name: "지하 문서금고", type: "장소", tone: "gold" },
    { name: "녹색 열쇠", type: "아이템", tone: "gold" },
  ],
  relations: [
    { from: "윤해주", to: "지하 문서금고", label: "열려고 함", state: "확인 필요" },
    { from: "민규백", to: "지하 문서금고", label: "계약을 취소함", state: "확인 필요" },
    { from: "윤해주", to: "서우", label: "연락함", state: "확인 완료" },
  ],
  reviews: [
    { title: "금고 개방 계약과 민규백의 일방적 취소 요구", body: "계약 당사자와 취소 권한이 원문에서 충분히 설명되었는지 확인해 주세요.", status: "확인 대기" },
    { title: "서우의 정확한 신분과 계약서 수신 경위", body: "현재 근거만으로는 인물 관계의 일부가 추론에 머뭅니다.", status: "확인 대기" },
  ],
  foreshadowing: [
    { title: "강태오의 끊어진 손가락이 생긴 이유", chapter: "2화", status: "검토 전" },
    { title: "기록 테이프의 숨은 내용과 폐기 이유", chapter: "4화", status: "검토 전" },
    { title: "녹색 열쇠의 용도와 은닉 이유", chapter: "4화", status: "검토 전" },
  ],
} as const;
