"""CandidateStore: id 해석, 조회하지 않은 항목의 기본 판정, 초안 검증, 응답 근거 구성."""

import pytest

from app.agent.context import CandidateStore, UnknownCandidateError
from app.agent.schemas import RecommendationDraft
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.common import ConditionCheck
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareResult
from app.schemas.media import GameMedia
from app.schemas.price import PriceQuote, PriceResult
from app.schemas.review import ReviewSummary


def test_resolve_keeps_order_and_rejects_unknown_ids(store):
    assert [g.igdb_id for g in store.resolve([3, 1, 3])] == [3, 1]
    with pytest.raises(UnknownCandidateError, match=r"\[99\]"):
        store.resolve([1, 99])


def test_add_candidates_ignores_duplicates_and_keeps_search_order(store):
    added = store.add_candidates(
        [GameCandidate(igdb_id=2, name="dup"), GameCandidate(igdb_id=4, name="new")]
    )
    assert [g.igdb_id for g in added] == [4]
    assert list(store.candidates) == [1, 2, 3, 4]
    assert store.candidates[2].name == "Game 2"


def test_unchecked_items_default_by_condition_presence():
    with_conditions = CandidateStore(GameConditions(max_price_krw=100, hardware={"cpu": "x"}))
    without = CandidateStore(GameConditions())
    for s in (with_conditions, without):
        s.add_candidates([GameCandidate(igdb_id=1, name="g")])
    assert with_conditions.evaluate(1).price.check.status == "unknown"
    assert with_conditions.evaluate(1).hardware.check.status == "unknown"
    assert without.evaluate(1).price.check.status == "skipped"
    assert without.evaluate(1).hardware.check.status == "skipped"
    assert not with_conditions.passes(1)
    assert without.passes(1)
    assert not with_conditions.checked(1)


def _check(store, igdb_id, price="met", hardware="met", amount=100):
    store.prices[igdb_id] = PriceResult(
        igdb_id=igdb_id,
        quote=PriceQuote(igdb_id=igdb_id, amount_krw=amount) if amount is not None else None,
        check=ConditionCheck(status=price, reason=f"가격 {price}"),
    )
    store.hardware[igdb_id] = HardwareResult(
        igdb_id=igdb_id, check=ConditionCheck(status=hardware, reason=f"사양 {hardware}")
    )


def test_validate_draft_lists_every_problem(store):
    _check(store, 1, price="unmet")
    _check(store, 2, hardware="unknown")
    _check(store, 3)
    problems = store.validate_draft(
        RecommendationDraft(recommended_igdb_ids=[1, 2, 3, 99], answer="  ")
    )
    assert any("[99]" in p for p in problems)
    assert any("2개 이하" in p for p in problems)
    assert any(p.startswith("Game 1(igdb_id 1)") and "가격 미충족" in p for p in problems)
    assert any(p.startswith("Game 2(igdb_id 2)") and "사양 확인 불가" in p for p in problems)
    assert any("answer" in p for p in problems)
    assert store.validate_draft(RecommendationDraft(recommended_igdb_ids=[3], answer="ok")) == []
    # 빈 추천도 유효하다 (조건에 맞는 게임이 없을 때)
    assert store.validate_draft(RecommendationDraft(recommended_igdb_ids=[], answer="없음")) == []


def test_passing_ids_lists_checked_passes_in_search_order():
    # 조건이 없으면 조회하지 않은 후보도 passes()는 참이지만, 판단한 적이 없으므로 넣지 않는다
    store = CandidateStore(GameConditions())
    store.add_candidates([GameCandidate(igdb_id=i, name=f"Game {i}") for i in (1, 2, 3, 4)])
    _check(store, 3, price="skipped", hardware="skipped", amount=None)
    _check(store, 1, price="skipped", hardware="skipped")
    _check(store, 2, price="unmet", hardware="skipped", amount=None)

    assert store.passes(4) and not store.checked(4)
    assert store.passing_ids() == [1, 3]


def test_unmentioned_ids_lists_recommended_games_missing_from_the_answer(store):
    draft = RecommendationDraft(recommended_igdb_ids=[1, 3, 3, 99], answer="Game 1을 추천합니다")

    # 1번은 본문에 있다. 99번은 후보가 아니라 validate_draft가 따로 잡는다
    assert store.unmentioned_ids(draft) == [3]
    assert store.unmentioned_ids(RecommendationDraft(recommended_igdb_ids=[], answer="없음")) == []


def test_build_evidence_excludes_only_checked_failures(store):
    _check(store, 1, price="unmet")
    _check(store, 3)
    store.reviews[1] = ReviewSummary(igdb_id=1, summary="r")
    store.media[1] = GameMedia(igdb_id=1)
    store.reviews[3] = ReviewSummary(igdb_id=3, summary="good")
    store.warnings.append("w")

    evidence = store.build_evidence([3])

    assert [g.game.igdb_id for g in evidence.games] == [3]
    assert evidence.games[0].review.summary == "good"
    # 2번은 조회한 적이 없어 판단하지 않았으므로 제외 목록에도 넣지 않는다
    assert [g.game.igdb_id for g in evidence.excluded_games] == [1]
    assert evidence.excluded_games[0].review is None
    assert evidence.excluded_games[0].media is None
    assert evidence.warnings == ["w"]
    assert evidence.conditions == store.conditions
