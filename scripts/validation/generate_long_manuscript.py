"""Generate a deterministic, Korean web-novel-sized fixture for local load tests."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output/validation/long-manuscript-20260913/episodes"
OUT.mkdir(parents=True, exist_ok=True)

scenes = [
    "안개가 항구의 지붕을 덮을 때 유나는 기록의 가장자리에 남은 붉은 실밥을 발견했다. 도윤은 아무 말 없이 등불을 들어 올렸고, 경비대의 교대 종이 세 번 울렸다.",
    "회백원의 서고에는 오래된 계약서가 층층이 쌓여 있었다. 유나는 같은 문장이 다른 잉크로 덧칠된 흔적을 따라가며 누군가 규칙을 바꾸려 했다는 사실을 알아냈다.",
    "마리아는 시장 골목에서 사라진 편지를 찾았다고 말했지만, 편지 봉인은 이미 한 번 뜯긴 뒤였다. 유나는 봉인검을 꺼내지 않고 먼저 손바닥의 상처를 살폈다.",
    "도윤은 유나에게 검을 쓰지 말라고 경고했다. 정식 계약자가 아니면 칼날이 주인을 거부한다는 규칙을 모두가 알고 있었지만, 종루 아래에서 들려온 목소리는 그 규칙을 비웃고 있었다.",
    "밤이 깊어질수록 항구의 물결은 일정한 간격으로 부두를 두드렸다. 유나는 그 소리가 암호라는 생각을 떨치지 못했고, 기록관의 지도에서 같은 간격의 표시를 찾아냈다.",
]

for episode in range(1, 11):
    paragraphs = [f"{episode}화. 붉은 편지의 항로\n"]
    for index in range(1, 45):
        scene = scenes[(episode + index) % len(scenes)]
        paragraphs.append(
            f"{scene} {episode}화의 {index}번째 기록에는 전날과 달라진 단서가 하나 더 적혀 있었다. "
            "유나는 인물들의 말과 행동을 따로 기록하고, 확정된 사실과 아직 확인하지 못한 추측을 구분했다. "
            "누군가의 기억은 다른 사람의 증언과 어긋났고, 그 차이는 다음 장면에서 다시 중요한 선택으로 돌아왔다. "
            "그녀는 원문 문장을 그대로 옮긴 뒤 시간과 장소를 표시했으며, 섣불리 결론을 내리지 않기로 했다. "
            "새벽이 오기 전까지 동료들은 두 갈래의 계획을 비교했고, 어느 쪽도 완전한 답이라고 말할 수 없었다.\n"
        )
    (OUT / f"episode-{episode:02d}.txt").write_text("\n".join(paragraphs), encoding="utf-8")

print({"episodes": 10, "total_chars": sum(p.stat().st_size for p in OUT.glob("*.txt")), "directory": str(OUT)})
