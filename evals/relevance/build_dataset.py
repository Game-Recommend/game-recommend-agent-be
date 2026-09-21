"""취향 적합도 평가 문항. 모델을 호출하지 않는다.

엔드투엔드 평가셋(evals/agent_e2e)은 100문항 중 60문항이 검색 조건이 없거나 장르·플랫폼 하나뿐이고,
취향이 뽑히는 문항은 6개다. 통과 후보 중 무엇을 고르든 질문에 맞는지 가릴 기준이 없다. 이 문항들은
**고를 기준이 있는 질문**이다.

넣지 않은 것
- 사양 조건: GPU·CPU 판정은 LLM이 하므로 대조 목록을 다시 계산할 때 판정이 달라질 수 있다.
- 평점 기준("Steam 평가 좋은"): 리뷰 점수 Tool은 에이전트 쪽에만 있어 비교가 도구 유무를 잰다.
- 무료 강제·아주 낮은 예산: 후보가 전부 탈락해 비교할 목록이 없다.
- 제외 표현("공포 빼고"): 질문 분해가 흔들리는 자리라 선택이 아니라 파서를 재게 된다.

    .venv/bin/python evals/relevance/build_dataset.py
"""

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent

TASTE = [
    "스토리가 탄탄해서 몰입할 수 있는 게임 추천해줘",
    "분위기 있고 세계관이 깊은 게임 알려줘",
    "머리를 많이 써야 하는 게임이 좋아",
    "아무 생각 없이 시원하게 때려 부수는 게임 추천해줘",
    "힐링되는 잔잔한 게임 찾고 있어",
    "어렵기로 유명해서 도전 욕구가 생기는 게임 알려줘",
    "짧게 끝낼 수 있는 완성도 높은 게임 추천해줘",
    "한 번 잡으면 몇백 시간은 할 수 있는 게임이 좋아",
    "자유도 높은 오픈월드 게임 추천해줘",
    "유머 코드가 있는 웃긴 게임 알려줘",
    "탐험하는 재미가 있는 게임 추천해줘",
    "뭔가 만들고 꾸미는 걸 좋아해. 그런 게임 추천해줘",
    "선택에 따라 이야기가 달라지는 게임이 좋아",
    "손맛 좋은 액션 게임 추천해줘",
    "감동적인 이야기로 여운이 남는 게임 알려줘",
    "전략 짜는 재미가 있는 게임 추천해줘",
]

SITUATION = [
    "퇴근하고 30분씩 가볍게 할 게임 추천해줘",
    "주말에 몰아서 엔딩까지 볼 만한 게임 알려줘",
    "게임을 거의 안 해 본 친구랑 같이 할 게임 추천해줘",
    "여자친구랑 둘이서 할 만한 게임 알려줘",
    "스트레스 풀고 싶을 때 할 게임 추천해줘",
    "오랜만에 게임을 다시 시작하려는데 입문용으로 좋은 게임 알려줘",
    "친구들이랑 디스코드 하면서 떠들기 좋은 게임 추천해줘",
    "잠들기 전에 조용히 할 게임 추천해줘",
    "부모님과 같이 할 수 있는 쉬운 게임 알려줘",
    "시험 끝나고 제대로 빠져들 게임 추천해줘",
    "컨트롤에 자신 없어도 즐길 수 있는 게임 추천해줘",
    "혼자 밤새 몰입할 게임 추천해줘",
]

MIXED = [
    "스토리가 중요한 RPG 3개 추천해줘",
    "3만 원 이하로 분위기 좋은 어드벤처 게임 추천해줘",
    "친구 한 명과 협동으로 깰 수 있는 퍼즐 게임 알려줘",
    "2만 원 이하로 가볍게 할 인디 게임 추천해줘",
    "SF 세계관의 스토리 게임 추천해줘",
    "혼자 할 전략 게임 중에 입문하기 쉬운 거 추천해줘",
    "5만 원 이하로 오래 즐길 수 있는 오픈월드 게임 알려줘",
    "친구 셋이서 온라인으로 웃으면서 할 게임 추천해줘",
    "엔딩까지 10시간 이하인 스토리 게임 추천해줘",
    "판타지 배경의 액션 RPG 2개만 추천해줘",
    "4만 원 이하로 도전적인 액션 게임 알려줘",
    "한 판이 짧은 경쟁 게임 추천해줘",
]

FAMILIES = [
    ("taste", "취향만 말한 질문. 검색 조건이 거의 없어 후보 풀이 같고, 고르는 일이 전부다", TASTE),
    ("situation", "상황을 말한 질문. 상황에서 취향을 읽어야 한다", SITUATION),
    ("mixed", "취향에 장르·예산·인원 같은 필수 조건이 함께 붙은 질문", MIXED),
]


def main() -> None:
    cases = []
    for family, _, questions in FAMILIES:
        for question in questions:
            cases.append({"id": f"R{len(cases) + 1:03}", "family": family, "question": question})

    (ROOT / "dataset.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    counts = Counter(item["family"] for item in cases)
    lines = [
        "# 취향 적합도 평가 문항",
        "",
        f"총 {len(cases)}문항. [build_dataset.py](build_dataset.py)가 만들고 "
        "[dataset.json](dataset.json)이 실행 데이터다. 정답 목록은 없다.",
        "",
        "| 계열 | 문항 수 | 무엇을 보는가 |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {name} | {counts[name]} | {what} |" for name, what, _ in FAMILIES]
    lines += ["", "## 문항", ""]
    lines += [f'- **{item["id"]}** ({item["family"]}): "{item["question"]}"' for item in cases]
    (ROOT / "questions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"문항 {len(cases)}개:", dict(counts))


if __name__ == "__main__":
    main()
