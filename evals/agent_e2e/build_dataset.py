"""에이전트 엔드투엔드 평가셋 100문항. 모델을 호출하거나 모델 출력으로 기대값을 만들지 않는다.

이 평가셋에는 "정답 추천 목록"이 없다. 열린 추천 질문 100개의 정답을 사람이 손으로 라벨링할
수 없기 때문이다. 대신 **응답만 보고 기계로 검증할 수 있는 조건**을 기대값으로 둔다.

    "3만 원 이하 게임 3개"  →  추천된 게임의 가격이 모두 3만 원 이하인가, 3개 이하인가

이 방식은 추천의 품질(적절한 게임을 골랐는가)을 재지 않는다. 계약 위반(사용자가 말한 필수
조건을 어긴 추천)만 잡는다. 품질은 답변 문단에 대한 LLM 심판이 따로 본다.

기대값은 "비어 있지 않아야 한다"를 주장하지 않는다. IGDB·Steam 데이터에 따라 조건을 만족하는
후보가 실제로 없을 수 있고, 그때 빈 목록과 경고를 내는 것이 옳은 동작이다. 대신 빈 목록이면
경고가 이유를 설명하는지 검사한다.
"""

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
cases: list[dict] = []


def case(family, question, expect, why, *, stages=None, note=None):
    item = {
        "id": f"E{len(cases) + 1:03}",
        "family": family,
        "question": question,
        "expect": expect,
        "why": why,
    }
    if stages:
        # 이 질문에서 반드시 실행돼야 하는 단계. 전 문항 공통 단계는 채점기가 따로 본다.
        item["required_stages"] = stages
    if note:
        item["note"] = note
    cases.append(item)


# ─────────────────────────────────────────────────────────────────────────────
# budget: 명시된 예산. 추천된 게임의 원화 가격이 상한 이하인지 본다.
# ─────────────────────────────────────────────────────────────────────────────
BUDGETS = [
    ("3만 원 이하로 살 수 있는 게임 추천해줘", 30000),
    ("2만 원 이하 게임 추천해줘", 20000),
    ("만 원 이하 게임 알려줘", 10000),
    ("5만 원 이하 게임 추천", 50000),
    ("15,000원 이하 게임 추천해줘", 15000),
    ("3만 원 이하 액션 게임 추천해줘", 30000),
    ("2만 원 이하 퍼즐 게임 알려줘", 20000),
    ("1만 원 이하 어드벤처 게임 추천", 10000),
    ("4만 원 이하 RPG 추천해줘", 40000),
    ("3만 원 이하 슈팅 게임 알려줘", 30000),
    ("2만 5천 원 이하 게임 추천해줘", 25000),
    ("6만 원 이하 게임 알려줘", 60000),
    ("5천 원 이하 게임 추천해줘", 5000),
    ("3만 원 이하 싱글 게임 추천", 30000),
    ("2만 원 이하 협동 게임 알려줘", 20000),
    ("만 오천 원 이하 아케이드 게임 추천", 15000),
    ("4만 원 이하 판타지 게임 알려줘", 40000),
    ("3만 원 이하 SF 게임 추천해줘", 30000),
    ("2만 원 이하 온라인 게임 알려줘", 20000),
    ("만 원 이하 짧은 게임 추천해줘", 10000),
]
for question, cap in BUDGETS:
    case(
        "budget",
        question,
        {"max_price_krw": cap},
        f"추천된 게임의 원화 가격이 모두 {cap:,}원 이하여야 한다",
        stages=["가격"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# free: 무료 강제. 가격이 0원이어야 한다.
# ─────────────────────────────────────────────────────────────────────────────
FREE = [
    "무료 게임만 추천해줘",
    "무료로 할 수 있는 게임만 알려줘",
    "돈 안 드는 게임만 추천",
    "공짜 게임만 찾아줘",
    "무료 액션 게임만 추천해줘",
    "무료 협동 게임만 알려줘",
    "무료 퍼즐 게임만 추천",
    "무료로 할 수 있는 RPG만 알려줘",
    "무료 온라인 게임만 추천해줘",
    "무료 파티 게임만 알려줘",
]
for question in FREE:
    case(
        "free",
        question,
        {"max_price_krw": 0, "require_free": True},
        "무료 강제 조건이므로 추천된 게임의 가격이 0원이어야 한다",
        stages=["가격"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# count: 개수 상한. 프롬프트가 개수를 목표치가 아니라 상한으로 정의한다.
# ─────────────────────────────────────────────────────────────────────────────
COUNTS = [
    ("게임 1개만 추천해줘", 1),
    ("게임 2개 추천해줘", 2),
    ("게임 3개만 알려줘", 3),
    ("게임 5개 추천해줘", 5),
    ("게임 4개 알려줘", 4),
    ("액션 게임 2개만 추천해줘", 2),
    ("퍼즐 게임 3개 알려줘", 3),
    ("RPG 1개만 추천해줘", 1),
    ("어드벤처 게임 4개 추천", 4),
    ("슈팅 게임 2개 알려줘", 2),
    ("협동 게임 3개만 추천해줘", 3),
    ("싱글 게임 5개 알려줘", 5),
    ("판타지 게임 2개 추천", 2),
    ("공포 게임 1개만 알려줘", 1),
    ("아케이드 게임 3개 추천해줘", 3),
]
for question, count in COUNTS:
    case(
        "count",
        question,
        {"max_games": count},
        f"추천 개수가 {count}개를 넘지 않아야 한다(개수는 상한이다)",
    )


# ─────────────────────────────────────────────────────────────────────────────
# exclude: 제외 장르. 에이전트가 search_games에 제외 조건을 넘겼는지 본다.
# excluded_genres는 에이전트(LLM)가 인자로 정하므로 빠뜨릴 수 있다.
# ─────────────────────────────────────────────────────────────────────────────
EXCLUDES = [
    ("공포 게임은 싫어. 게임 추천해줘", ["Horror"]),
    ("공포 빼고 게임 알려줘", ["Horror"]),
    ("무서운 게임 말고 추천해줘", ["Horror"]),
    ("공포 제외하고 어드벤처 게임 추천", ["Horror"]),
    ("공포는 안 돼. 액션 게임 알려줘", ["Horror"]),
    ("공포 게임 빼고 RPG 추천해줘", ["Horror"]),
    ("액션은 제외하고 퍼즐 게임 알려줘", ["Action"]),
    ("슈팅 게임은 싫어. 다른 거 추천해줘", ["Shooter"]),
    ("공포와 슈팅은 빼고 게임 추천", ["Horror", "Shooter"]),
    ("퍼즐은 제외하고 게임 알려줘", ["Puzzle"]),
    ("공포 게임은 못 하겠어. 협동 게임 추천해줘", ["Horror"]),
    ("액션 게임 말고 추천해줘", ["Action"]),
    ("공포 빼고 3만 원 이하 게임 알려줘", ["Horror"]),
    ("슈팅 제외하고 게임 2개 추천해줘", ["Shooter"]),
    ("공포 게임은 싫고 혼자 할 게임 추천", ["Horror"]),
]
for question, excluded in EXCLUDES:
    expect = {"exclude_genres": excluded}
    if "3만 원" in question:
        expect["max_price_krw"] = 30000
    if "2개" in question:
        expect["max_games"] = 2
    case(
        "exclude",
        question,
        expect,
        f"추천된 게임의 장르·테마에 {', '.join(excluded)}가 없어야 한다",
    )


# ─────────────────────────────────────────────────────────────────────────────
# hardware: 사용자 사양. 사양 판정이 met이나 skipped여야 한다.
# 루트 README의 "실패나 누락은 필수 조건 통과로 처리하지 않는다"를 검사한다.
# ─────────────────────────────────────────────────────────────────────────────
HARDWARE = [
    "RTX 3060, RAM 16GB PC인데 할 게임 추천해줘",
    "i5-12400, RAM 8GB인데 돌아갈 게임 알려줘",
    "GTX 1650, RAM 8GB 노트북이야. 게임 추천해줘",
    "Ryzen 5 5600, RX 6600 쓰는데 게임 추천",
    "RTX 4060, RAM 32GB PC로 할 게임 알려줘",
    "i7-13700, RTX 4070 쓰는데 게임 추천해줘",
    "RAM 16GB, GTX 1060인데 할 만한 게임",
    "i3-10100, RAM 8GB로 돌아가는 게임 알려줘",
    "RTX 3070, RAM 16GB인데 3만 원 이하 게임 추천해줘",
    "GTX 1660, RAM 16GB PC로 액션 게임 알려줘",
    "RTX 3060 Ti, RAM 16GB인데 게임 2개 추천",
    "Ryzen 7 5800X, RTX 3080 쓰는데 게임 추천해줘",
    "i5-11400, RAM 8GB인데 무료 게임만 알려줘",
    "RX 580, RAM 8GB로 할 게임 추천",
    "RTX 4090, RAM 64GB PC인데 게임 알려줘",
]
for question in HARDWARE:
    expect: dict = {"hardware_checked": True}
    if "3만 원" in question:
        expect["max_price_krw"] = 30000
    if "2개" in question:
        expect["max_games"] = 2
    if "무료" in question:
        expect["max_price_krw"] = 0
        expect["require_free"] = True
    case(
        "hardware",
        question,
        expect,
        "사양 판정이 met이나 skipped여야 한다. unmet·unknown인 게임은 추천에 들어갈 수 없다",
        stages=["하드웨어"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# tight: 아주 낮은 예산. 빈 목록을 요구하지 않고, 낸 추천이 조건을 지키는지만 본다.
# ─────────────────────────────────────────────────────────────────────────────
TIGHT = [
    ("1000원 이하 게임 추천해줘", 1000),
    ("2000원 이하 게임 알려줘", 2000),
    ("500원 이하 게임 추천", 500),
    ("3000원 이하 RPG 추천해줘", 3000),
    ("1000원 이하 액션 게임 2개 알려줘", 1000),
]
for question, cap in TIGHT:
    expect = {"max_price_krw": cap}
    if "2개" in question:
        expect["max_games"] = 2
    case(
        "tight",
        question,
        expect,
        f"{cap:,}원 이하라는 조건을 지키거나, 조건에 맞는 후보가 없다고 경고해야 한다",
        stages=["가격"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# combined: 루트 README의 예상 질문 5개 + 복합 조건 15개
# ─────────────────────────────────────────────────────────────────────────────
case(
    "combined",
    "내 노트북이 i5-1240P, RAM 16GB, 내장그래픽인데 원활하게 할 수 있는 게임 중에서 "
    "평점 좋은 게임 추천해줘.",
    {"hardware_checked": True},
    "README 예상 질문(하드웨어)",
    stages=["하드웨어"],
)
case(
    "combined",
    "친구 4명이서 온라인으로 같이 할 게임을 찾고 있어. 경쟁보다는 협동 위주였으면 좋겠고 "
    "한 판이 너무 길지 않았으면 좋겠어.",
    {},
    "README 예상 질문(멀티플레이+인원). 구조화 상한이 없어 공통 불변식만 본다",
)
case(
    "combined",
    "지금 2만 원 이하로 살 수 있는 게임 중에서 스토리가 중요한 RPG 추천해줘. "
    "턴제 게임은 별로 안 좋아해.",
    {"max_price_krw": 20000},
    "README 예상 질문(가격+취향)",
    stages=["가격"],
)
case(
    "combined",
    "취업 준비하면서 가볍게 할 게임을 찾고 있어. 한 번에 30분~1시간 정도 하기 좋고, "
    "전체 플레이타임도 15시간을 넘지 않는 싱글 게임이면 좋겠어.",
    {},
    "README 예상 질문(플레이타임+장르). 플레이타임은 IGDB 값이 없을 수 있어 주장하지 않는다",
)
case(
    "combined",
    "RTX 3060, RAM 16GB PC를 사용하고 있어. 친구 한 명과 온라인으로 같이 할 수 있고, "
    "공포 게임은 싫어. 3만 원 이하이면서 Steam 평가가 좋은 게임 3개만 추천해줘.",
    {
        "max_price_krw": 30000,
        "max_games": 3,
        "exclude_genres": ["Horror"],
        "hardware_checked": True,
    },
    "README 예상 질문(복합, 데모용). 가격·개수·제외·사양이 한 번에 걸린다",
    stages=["가격", "하드웨어"],
)

COMBINED_MORE = [
    (
        "RTX 4060으로 할 3만 원 이하 액션 게임 3개 추천해줘",
        {"max_price_krw": 30000, "max_games": 3, "hardware_checked": True},
        ["가격", "하드웨어"],
    ),
    (
        "혼자 할 수 있는 2만 원 이하 어드벤처 게임 2개 알려줘",
        {"max_price_krw": 20000, "max_games": 2},
        ["가격"],
    ),
    (
        "친구 세 명이서 할 무료 파티 게임만 3개 추천",
        {"max_price_krw": 0, "require_free": True, "max_games": 3},
        ["가격"],
    ),
    (
        "i5-12400, RAM 8GB인데 2만 원 이하 퍼즐 게임 5개 추천",
        {"max_price_krw": 20000, "max_games": 5, "hardware_checked": True},
        ["가격", "하드웨어"],
    ),
    (
        "온라인으로 친구와 경쟁하는 3만 원 이하 슈팅 게임 4개 추천해줘",
        {"max_price_krw": 30000, "max_games": 4},
        ["가격"],
    ),
    (
        "공포 빼고 1만 원 이하 게임 2개 알려줘",
        {"max_price_krw": 10000, "max_games": 2, "exclude_genres": ["Horror"]},
        ["가격"],
    ),
    (
        "GTX 1650 노트북인데 무료 게임만 2개 추천해줘",
        {"max_price_krw": 0, "require_free": True, "max_games": 2, "hardware_checked": True},
        ["가격", "하드웨어"],
    ),
    (
        "RTX 3070, RAM 16GB PC로 할 공포 게임 2개 추천",
        {"max_games": 2, "hardware_checked": True},
        ["하드웨어"],
    ),
    (
        "5만 원 이하 판타지 RPG 중에 공포는 빼고 3개 알려줘",
        {"max_price_krw": 50000, "max_games": 3, "exclude_genres": ["Horror"]},
        ["가격"],
    ),
    (
        "혼자 할 3만 원 이하 스토리 중심 게임 1개만 추천해줘",
        {"max_price_krw": 30000, "max_games": 1},
        ["가격"],
    ),
    (
        "RAM 8GB 저사양 PC로 할 만 원 이하 게임 3개 알려줘",
        {"max_price_krw": 10000, "max_games": 3, "hardware_checked": True},
        ["가격", "하드웨어"],
    ),
    (
        "친구 한 명과 한 화면에서 할 2만 원 이하 협동 게임 2개 추천",
        {"max_price_krw": 20000, "max_games": 2},
        ["가격"],
    ),
    (
        "슈팅 제외하고 4만 원 이하 액션 게임 3개 알려줘",
        {"max_price_krw": 40000, "max_games": 3, "exclude_genres": ["Shooter"]},
        ["가격"],
    ),
    (
        "i7-13700, RTX 4070인데 무료 온라인 게임만 3개 추천해줘",
        {"max_price_krw": 0, "require_free": True, "max_games": 3, "hardware_checked": True},
        ["가격", "하드웨어"],
    ),
    (
        "공포도 슈팅도 싫어. 2만 원 이하 게임 2개만 추천해줘",
        {
            "max_price_krw": 20000,
            "max_games": 2,
            "exclude_genres": ["Horror", "Shooter"],
        },
        ["가격"],
    ),
]
for question, expect, stages in COMBINED_MORE:
    case("combined", question, expect, "복합 조건: 여러 필수 조건이 한 번에 걸린다", stages=stages)


FAMILIES = [
    ("budget", "명시 예산 상한을 추천 결과가 지키는가"),
    ("free", "무료 강제 조건에서 가격이 0원인가"),
    ("count", "추천 개수가 상한을 넘지 않는가"),
    ("exclude", "제외 장르가 검색에 전달돼 추천에서 빠지는가"),
    ("hardware", "사양 판정이 met·skipped인 게임만 추천하는가"),
    ("tight", "아주 낮은 예산에서도 조건을 지키거나 경고하는가"),
    ("combined", "여러 필수 조건이 한 번에 걸릴 때"),
]


def main() -> None:
    counts = Counter(item["family"] for item in cases)
    unknown = set(counts) - {name for name, _ in FAMILIES}
    if unknown:
        raise SystemExit(f"FAMILIES에 없는 계열: {sorted(unknown)}")

    (ROOT / "dataset.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# 에이전트 엔드투엔드 평가 문항",
        "",
        f"총 {len(cases)}문항. [build_dataset.py](build_dataset.py)가 만들고 "
        "[dataset.json](dataset.json)이 실행 데이터다.",
        "",
        "이 평가셋에는 정답 추천 목록이 없다. 응답만 보고 기계로 검증할 수 있는 "
        "조건만 기대값으로 둔다.",
        "자세한 내용은 [README.md](README.md)에 있다.",
        "",
        "| 계열 | 문항 수 | 무엇을 보는가 |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {name} | {counts[name]} | {what} |" for name, what in FAMILIES]
    lines += ["", "## 문항", ""]
    for item in cases:
        lines.append(f"- **{item['id']}** ({item['family']}): \"{item['question']}\"")
        lines.append(f"  - 검사: {item['why']}")
    (ROOT / "questions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"문항 {len(cases)}개")
    for name, _ in FAMILIES:
        print(f"  {name}: {counts[name]}")


if __name__ == "__main__":
    main()
