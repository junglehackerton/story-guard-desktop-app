from backend.app.pipeline.candidates import collect_story_candidates


def test_repeated_named_clue_is_kept_as_foreshadowing_candidate() -> None:
    text = (
        "유나는 사라진 편지를 단서로 기록했다.\n"
        "며칠 뒤 사라진 편지의 빈칸을 다시 확인했다."
    )

    payload = collect_story_candidates(text)

    candidates = [
        entity for entity in payload["entities"] if entity["type"] == "foreshadowing"
    ]
    assert [entity["name"] for entity in candidates] == ["사라진 편지"]
