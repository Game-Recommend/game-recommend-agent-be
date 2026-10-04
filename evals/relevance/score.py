"""취향 적합도 평가의 순수 로직: 대조 목록, 심판 판정 결합, 집계. API를 부르지 않는다.

에이전트가 고른 목록을 **같은 통과 후보를 검색 순서(인기순)대로 자른 목록**과 비교한다. 뒤쪽은 고정
파이프라인의 선택 규칙이다. 두 목록은 같은 후보 풀, 같은 판정 결과에서 나오므로 검색 품질·도구
유무·빈 추천의 영향을 받지 않고 "무엇을 고를지를 LLM에 맡긴 효과"만 남는다.

원본 기록(`run_original.py`)이 있으면 **원본 저장소를 실제로 돌려 나온 목록**과도 비교한다. 이쪽은
후보 풀부터 다르므로 검색 수정·도구 유무의 효과가 함께 들어 있다.
"""

from collections import Counter
from typing import Literal

from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareResult
from app.schemas.price import PriceResult

# 추천에 들어갈 수 있는 판정 상태(app/agent/context.py의 PASSING과 같다)
PASSING = {"met", "skipped"}

Side = Literal["agent", "baseline", "original", "tie"]
# same=두 목록이 같은 게임이다, empty=에이전트가 추천을 내지 않았다
Outcome = Literal["agent", "baseline", "tie", "same", "empty"]
OUTCOMES = ("agent", "baseline", "tie", "same", "empty")
# 실제 원본과의 비교. original_empty=원본이 추천을 내지 않았다
VersusOriginal = Literal["agent", "original", "tie", "same", "empty", "original_empty"]
ORIGINAL_OUTCOMES = ("agent", "original", "tie", "same", "empty", "original_empty")


def baseline_pick(
    candidates: list[GameCandidate],
    prices: dict[int, PriceResult],
    hardware: dict[int, HardwareResult],
    count: int,
) -> list[GameCandidate]:
    """고정 파이프라인이 했을 선택. 가격·사양 판정을 통과한 후보를 검색 순서대로 count개."""
    passing = [
        game
        for game in candidates
        if game.igdb_id in prices
        and game.igdb_id in hardware
        and prices[game.igdb_id].check.status in PASSING
        and hardware[game.igdb_id].check.status in PASSING
    ]
    return passing[:count]


def to_side(winner: str, agent_is: str, other: Side = "baseline") -> Side:
    """심판이 고른 자리(A/B)를 누구의 목록인지로 바꾼다. other는 에이전트와 겨룬 쪽이다."""
    if winner == "tie":
        return "tie"
    return "agent" if winner == agent_is else other


def combine(first: Side, second: Side) -> Side:
    """자리를 바꿔 두 번 물은 판정을 합친다.

    LLM 심판은 앞에 놓인 쪽을 고르는 경향이 있다. 두 번 모두 같은 쪽을 골랐을 때만 그쪽의 승리로
    보고, 엇갈리면 비긴 것으로 본다.
    """
    return first if first == second else "tie"


def overlap(agent_ids: list[int], baseline_ids: list[int]) -> float:
    """두 목록의 Jaccard 겹침. 1이면 같은 게임이다."""
    union = set(agent_ids) | set(baseline_ids)
    return round(len(set(agent_ids) & set(baseline_ids)) / len(union), 4) if union else 1.0


def parse_original(record: dict) -> tuple[list[GameCandidate], dict[int, int | None]]:
    """`run_original.py`가 남긴 한 문항에서 원본의 추천 목록과 원화 가격을 읽는다."""
    rows = record.get("games", [])
    games = [GameCandidate.model_validate(row["game"]) for row in rows]
    return games, {game.igdb_id: row["amount_krw"] for game, row in zip(games, rows, strict=True)}


def versus_original_outcome(agent_ids: list[int], original_ids: list[int]) -> VersusOriginal | None:
    """심판 없이 정해지는 결과. None이면 심판에게 묻는다.

    빈 추천은 어느 쪽이든 승패로 세지 않고 따로 센다. 목록이 없으면 무엇이 질문에 맞는지
    견줄 수 없다.
    """
    if not agent_ids:
        return "empty"
    if not original_ids:
        return "original_empty"
    if set(agent_ids) == set(original_ids):
        return "same"
    return None


def summarize_original(records: list[dict]) -> dict | None:
    """실제 원본과의 비교 집계. 원본 기록 없이 돌렸으면 None이다.

    에이전트 실행이나 원본 실행이 오류로 끝난 문항은 분모에서 뺀다.
    """
    if not any("original" in record for record in records):
        return None
    scored = [
        record
        for record in records
        if not record.get("error") and "original" in record and "error" not in record["original"]
    ]
    outcomes = Counter(record["original"]["outcome"] for record in scored)
    decided = outcomes["agent"] + outcomes["original"]
    judged = [
        record["original"]
        for record in scored
        if record["original"]["outcome"] in ("agent", "original", "tie")
    ]

    families: dict[str, Counter] = {}
    for record in scored:
        families.setdefault(record["family"], Counter())[record["original"]["outcome"]] += 1

    return {
        "scored": len(scored),
        "errors": len(records) - len(scored),
        "outcomes": {name: outcomes[name] for name in ORIGINAL_OUTCOMES},
        "agent_win_rate": round(outcomes["agent"] / decided, 4) if decided else None,
        "overlap_mean": round(sum(r["overlap"] for r in judged) / len(judged), 4)
        if judged
        else None,
        "by_family": {
            name: {key: counts[key] for key in ORIGINAL_OUTCOMES}
            for name, counts in sorted(families.items())
        },
    }


def summarize(records: list[dict]) -> dict:
    """오류로 끝난 문항은 분모에서 뺀다(evals/agent_e2e와 같은 관례)."""
    scored = [record for record in records if not record.get("error")]
    outcomes = Counter(record["outcome"] for record in scored)
    decided = outcomes["agent"] + outcomes["baseline"]
    compared = [record for record in scored if record["outcome"] not in ("empty", "same")]

    families: dict[str, Counter] = {}
    for record in scored:
        families.setdefault(record["family"], Counter())[record["outcome"]] += 1

    summary = {
        "attempted": len(records),
        "scored": len(scored),
        "errors": len(records) - len(scored),
        "outcomes": {name: outcomes[name] for name in OUTCOMES},
        # 심판이 어느 한쪽을 고른 문항 중 에이전트가 이긴 비율. 0.5면 차이가 없다
        "agent_win_rate": round(outcomes["agent"] / decided, 4) if decided else None,
        # 에이전트의 선택이 인기순과 달랐던 문항의 비율. 낮으면 고를 여지가 없었다는 뜻이다
        "changed_rate": round(len(compared) / len(scored), 4) if scored else None,
        "overlap_mean": round(sum(r["overlap"] for r in compared) / len(compared), 4)
        if compared
        else None,
        "pool_mismatches": sum(1 for record in scored if record.get("pool_mismatch")),
        "by_family": {
            name: {key: counts[key] for key in OUTCOMES}
            for name, counts in sorted(families.items())
        },
    }
    if (versus := summarize_original(records)) is not None:
        summary["original"] = versus
    return summary
