"""취향 적합도 평가의 순수 로직: 대조 목록, 심판 판정 결합, 집계. API를 부르지 않는다.

에이전트가 고른 목록을 **같은 통과 후보를 검색 순서(인기순)대로 자른 목록**과 비교한다. 뒤쪽은 고정
파이프라인이 했을 선택이다. 두 목록은 같은 후보 풀, 같은 판정 결과에서 나오므로 검색 품질·도구
유무·빈 추천의 영향을 받지 않고 "무엇을 고를지를 LLM에 맡긴 효과"만 남는다.
"""

from collections import Counter
from typing import Literal

from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareResult
from app.schemas.price import PriceResult

# 추천에 들어갈 수 있는 판정 상태(app/agent/context.py의 PASSING과 같다)
PASSING = {"met", "skipped"}

Side = Literal["agent", "baseline", "tie"]
# same=두 목록이 같은 게임이다, empty=에이전트가 추천을 내지 않았다
Outcome = Literal["agent", "baseline", "tie", "same", "empty"]
OUTCOMES = ("agent", "baseline", "tie", "same", "empty")


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


def to_side(winner: str, agent_is: str) -> Side:
    """심판이 고른 자리(A/B)를 누구의 목록인지로 바꾼다."""
    if winner == "tie":
        return "tie"
    return "agent" if winner == agent_is else "baseline"


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


def summarize(records: list[dict]) -> dict:
    """오류로 끝난 문항은 분모에서 뺀다(evals/agent_e2e와 같은 관례)."""
    scored = [record for record in records if not record.get("error")]
    outcomes = Counter(record["outcome"] for record in scored)
    decided = outcomes["agent"] + outcomes["baseline"]
    compared = [record for record in scored if record["outcome"] not in ("empty", "same")]

    families: dict[str, Counter] = {}
    for record in scored:
        families.setdefault(record["family"], Counter())[record["outcome"]] += 1

    return {
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
