"""Deprecated synthetic fixture generator; do not use for E2E validation.

Use model-authored files with validate_authored_manuscript.py instead.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output/validation/long-manuscript-20260913/episodes"
OUT.mkdir(parents=True, exist_ok=True)

characters = ["유나", "도윤", "서린", "하린", "마루", "마리아"]
places = ["안개항의 세관 창고", "회백원 서고", "흰 재 시장", "종루 아래 골목", "검은 부두", "우물 광장", "폐역 승강장", "삭제 목록 보관실", "북쪽 수문", "유리 온실", "파도 관측소", "낡은 극장 뒤편"]
arcs = [
    ("사라진 선적 장부", "유나는 안개항에서 봉인된 장부의 행방을 쫓는다", "도윤이 세관 창고 열쇠를 숨겼다는 소문"),
    ("서고의 빈칸", "서린은 회백원 서고의 삭제 목록에서 자신의 이름을 발견한다", "기록관 마리아가 오래된 규칙의 예외를 알고 있다는 사실"),
    ("붉은 지도", "하린은 시장의 지도에 표시된 금지 구역으로 몰래 들어간다", "지도 가장자리의 붉은 실밥이 북쪽 수문을 가리킨다는 단서"),
    ("계약의 대가", "유나는 봉인검을 되찾기 위해 정식 계약의 조건을 협상한다", "서명하지 않은 사람도 검을 들 수 있다는 의문의 목격담"),
    ("검은 파도", "도윤은 밤마다 반복되는 파도 간격을 기록하며 실종 사건을 연결한다", "관측소 시계가 누군가에 의해 네 분 늦춰졌다는 증거"),
    ("온실의 증언", "마리아는 유리 온실에서 서로 다른 기억을 가진 증인들을 대질한다", "하린이 감춘 편지 한 장이 두 증언의 모순을 설명한다"),
    ("폐역의 승강장", "서린은 폐역에서 정차하지 않은 열차의 흔적을 조사한다", "삭제 목록의 빈 줄과 젖은 표지판 숫자가 같은 시각을 가리킨다"),
    ("찢긴 장", "마루는 보관실의 찢긴 장을 이어 붙여 봉인의 원래 목적을 복원한다", "예외 조항이 계약자의 자격보다 먼저 쓰였다는 사실"),
    ("수문 개방", "일행은 북쪽 수문을 열어 잠긴 항로를 되살릴지 결정해야 한다", "봉인검의 사용 기록이 과거의 배신자를 지목한다"),
    ("첫 항해", "유나는 모든 기록을 대조한 뒤 새벽의 항해에서 진실을 공개한다", "누락된 이름을 기록에 되돌릴지 말지는 유나의 선택으로 남는다"),
]
dialogues = [("유나", "기억이 아니라 기록을 따라가요. 기록은 틀릴 수 있어도, 틀린 순간을 찾을 수 있으니까요."), ("도윤", "열쇠를 건넨 건 나지만, 문을 연 사람이 누구인지는 아직 말하지 않았어."), ("서린", "빈 줄을 지운 흔적으로 취급하면 안 돼요. 누군가 남겨 둔 자리일 수도 있어요."), ("하린", "계약서에 없는 약속은 약속이 아니야. 그래도 왜 모두가 그 말을 믿었는지는 따져 봐야 해."), ("마루", "시계가 늦은 게 아니라 종이 먼저 울렸다면, 우리가 본 순서가 전부 바뀌어."), ("마리아", "예외를 숨기면 규칙이 단단해지는 게 아니라, 다음 사람을 함정에 빠뜨리는 거예요.")]
evidence = ["낡은 표지판 뒤에서 봉투를 꺼냈다", "젖은 장부의 가장자리에서 서로 다른 잉크 두 색을 비교했다", "바닥에 남은 발자국을 수문 쪽 지도와 겹쳐 보았다", "증언자의 말이 끊긴 시각을 종루의 녹음과 맞췄다", "찢긴 종이의 섬유 방향을 맞물려 원래 순서를 추정했다", "보관함 번호와 선적 표식의 숫자를 대조했다"]
beats = [
    "경비병의 교대가 끝난 틈에 창문으로 들어갔다", "비에 젖은 편지를 난로 가까이 가져가 숨은 글씨를 드러냈다", "마루 밑에서 발견한 동전의 문양을 오래된 지도와 비교했다", "닫힌 매표소의 유리 너머로 누군가 남긴 손짓을 보았다", "서로 다른 두 증인의 말에서 공통으로 빠진 시간을 표시했다", "부서진 나침반을 분해해 안쪽에 감긴 붉은 실을 꺼냈다", "수문 벽에 남은 긁힌 자국을 자로 재고 방향을 기록했다", "낯선 발자국이 물가에서 갑자기 사라진 지점을 확인했다", "봉투의 밀랍 문양을 확대해 가문의 인장과 대조했다", "낡은 녹음기에서 잡음을 걷어 내자 짧은 이름이 들렸다", "서고의 사다리를 옮기다 뒤쪽 벽에 숨은 문을 찾았다", "시장 상인이 건넨 영수증에서 지난달 날짜를 발견했다", "온실의 유리마다 맺힌 물방울 방향이 달랐다", "철로 아래 자갈 틈에서 열차 시간표 조각을 주웠다", "도윤의 수첩에 없는 페이지가 누군가의 가방에서 나왔다", "서린은 같은 문장을 세 필체로 옮겨 적어 차이를 찾았다", "하린은 봉인검 손잡이의 흠집을 최근 사진과 겹쳤다", "마리아는 증언을 멈추고 창밖 종소리부터 세었다", "마루는 지도에 표시되지 않은 계단을 직접 내려갔다", "유나는 모두가 침묵한 순간에만 들리는 기계음을 기록했다",
]

def josa(name: str, pair: str) -> str:
    """Return a readable particle for the named character."""
    # All fixture names end in a vowel except 도윤/서린/하린/마루/마리아.
    has_batchim = name in {"도윤", "서린", "하린"}
    return {"은는": "은" if has_batchim else "는", "이가": "이" if has_batchim else "가"}[pair]

def object_josa(word: str) -> str:
    return "을" if word[-1] in "각간갇갈감갑값갓강개객갱거걱건걸검겁것겉게격견결겸경계고곡곤골곰공곽관괄광괴굉교구국군굴굶궁권궐귀규균극근글금급긍기긴길김깃" else "를"

for episode, (title, objective, clue) in enumerate(arcs, 1):
    paragraphs = [f"{episode}화. {title}\n", f"{objective}. 이번 회차의 추적 대상은 {clue}.\n"]
    for index in range(1, 61):
        lead = characters[(episode * 2 + index) % len(characters)]
        partner = characters[(episode + index * 3 + 1) % len(characters)]
        place = places[(episode + index * 2) % len(places)]
        speaker, quote = dialogues[(episode + index) % len(dialogues)]
        quote = quote.replace(".", ",") + f" {episode}화 {index}번째로 확인한 장소는 {place}였어."
        clock, minute = 6 + ((episode * 3 + index) % 17), (episode * 11 + index * 7) % 60
        beat = beats[(episode * 7 + index) % len(beats)] + f" (현장 기록 {episode}-{index})"
        if index % 4 == 1:
            turn = f"{lead}{josa(lead, '은는')} {partner}에게 바로 결론을 말하지 않고 {place}에서 {evidence[(episode + index) % 6]}"
        elif index % 4 == 2:
            turn = f"{partner}{josa(partner, '이가')} {place}의 반대편 통로에서 나타나자 {lead}{josa(lead, '은는')} 기록을 다시 확인한 뒤에야 고개를 들었다"
        elif index % 4 == 3:
            turn = f"둘은 {place}의 난간에 자료를 펼쳤고, {lead}{josa(lead, '이가')} {evidence[(episode + index) % 6]} 하자 숨겨진 순서가 드러났다"
        else:
            turn = f"{lead}{josa(lead, '은는')} {evidence[(episode + index) % 6]}고 적은 뒤 그 메모를 {partner}에게만 보여 주었다"
        consequence = [f"그 선택으로 다음 단서는 {places[(episode + index + 3) % len(places)]}로 옮겨 갔다", "결과를 확정하지 못한 채 봉투에 '대조 필요'라고 적고 시각을 남겼다", "새로 확인된 사실은 일행의 계획을 한 단계 앞당겼다", "설명되지 않은 빈칸 하나가 다음 회차의 질문으로 남았다"][(episode + index) % 4]
        paragraphs.append(f"{beat}. {turn} (기록 {episode}-{index}). {episode}화 {clock}시 {minute:02d}분, {speaker}{josa(speaker, '이가')} 말했다. \"{quote}\" {consequence}.\n")
    (OUT / f"episode-{episode:02d}.txt").write_text("\n".join(paragraphs), encoding="utf-8")

print({"episodes": 10, "total_chars": sum(p.stat().st_size for p in OUT.glob("*.txt")), "directory": str(OUT)})
