"""채점기 검사. API를 부르지 않는다."""

import json
import pathlib
from pathlib import Path

import app
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.common import ConditionCheck
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareResult, HardwareSpecs
from app.schemas.price import PriceQuote, PriceResult
from app.schemas.recommendation import EvaluatedGame, RecommendationResponse
from evals.agent_e2e.judge import build_evidence
from evals.agent_e2e.rescore import rescore_record
from evals.agent_e2e.run_eval import summarize
from evals.agent_e2e.score import (
    BASE_STAGES,
    check_answer_format,
    check_constraints,
    check_overlooked_candidates,
    check_trajectory,
    count_sentences,
    detect_profile,
    passing_count,
    score_case,
)

DATA = json.loads((Path(__file__).parent / "dataset.json").read_text(encoding="utf-8"))
BY_ID = {item["id"]: item for item in DATA}

OK_STAGES = [
    {"t": 0.0, "stage": "질문 분해", "status": "started", "detail": None},
    {"t": 1.0, "stage": "질문 분해", "status": "completed", "detail": None},
    {"t": 1.0, "stage": "에이전트 추론", "status": "started", "detail": None},
    {"t": 2.0, "stage": "게임 검색", "status": "started", "detail": None},
    {"t": 3.0, "stage": "게임 검색", "status": "completed", "detail": "후보 30개"},
    {"t": 4.0, "stage": "가격", "status": "started", "detail": None},
    {"t": 5.0, "stage": "가격", "status": "completed", "detail": None},
    {"t": 5.0, "stage": "하드웨어", "status": "started", "detail": None},
    {"t": 6.0, "stage": "하드웨어", "status": "completed", "detail": None},
    {"t": 7.0, "stage": "에이전트 추론", "status": "completed", "detail": "도구 호출 3회"},
]


def game(
    igdb_id=1,
    name="테스트 게임",
    price_krw=10000,
    price_status="met",
    hardware_status="met",
    genres=(),
    themes=(),
):
    return EvaluatedGame(
        game=GameCandidate(igdb_id=igdb_id, name=name, genres=list(genres), themes=list(themes)),
        price=PriceResult(
            igdb_id=igdb_id,
            quote=None
            if price_krw is None
            else PriceQuote(igdb_id=igdb_id, amount_krw=price_krw),
            check=ConditionCheck(status=price_status, reason="테스트"),
        ),
        hardware=HardwareResult(
            igdb_id=igdb_id, check=ConditionCheck(status=hardware_status, reason="테스트")
        ),
    )


def response(games, answer="첫 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다.", **kwargs):
    conditions = GameConditions(**kwargs.pop("conditions", {}))
    return RecommendationResponse(
        conditions=conditions, games=games, answer=answer, **kwargs
    )


def test_dataset_has_100_unique_cases():
    assert len(DATA) == 100
    assert len({item["id"] for item in DATA}) == 100


def test_every_case_records_why():
    assert all(item["why"] for item in DATA)


def test_expect_keys_are_known():
    """기대값에 오타가 있으면 채점이 조용히 통과해 버린다."""
    allowed = {
        "max_price_krw",
        "require_free",
        "max_games",
        "exclude_genres",
        "hardware_checked",
    }
    for item in DATA:
        unknown = set(item["expect"]) - allowed
        assert not unknown, f"{item['id']}의 기대값에 모르는 키: {unknown}"


def test_count_sentences():
    assert count_sentences("한 문장입니다.") == 1
    assert count_sentences("하나. 둘. 셋.") == 3


def test_price_within_budget_passes():
    item = BY_ID["E001"]  # 3만 원 이하
    assert item["expect"]["max_price_krw"] == 30000
    assert check_constraints(item, response([game(price_krw=29000)])) == []


def test_price_over_budget_fails():
    item = BY_ID["E001"]
    problems = check_constraints(item, response([game(price_krw=31000)]))
    assert any("상한" in problem for problem in problems)


def test_missing_quote_with_budget_fails():
    item = BY_ID["E001"]
    problems = check_constraints(item, response([game(price_krw=None)]))
    assert any("원화 가격이 없다" in problem for problem in problems)


def test_unmet_price_status_cannot_be_recommended():
    item = BY_ID["E001"]
    problems = check_constraints(item, response([game(price_krw=1000, price_status="unmet")]))
    assert any("가격 판정이 unmet" in problem for problem in problems)


def test_unknown_hardware_status_cannot_be_recommended():
    item = BY_ID["E001"]
    problems = check_constraints(
        item, response([game(price_krw=1000, hardware_status="unknown")])
    )
    assert any("사양 판정이 unknown" in problem for problem in problems)


def test_duplicate_igdb_id_fails():
    item = BY_ID["E001"]
    problems = check_constraints(
        item, response([game(igdb_id=7, price_krw=100), game(igdb_id=7, price_krw=100)])
    )
    assert any("중복" in problem for problem in problems)


def test_empty_recommendation_without_warning_fails():
    item = BY_ID["E001"]
    problems = check_constraints(item, response([]))
    assert any("경고가 없다" in problem for problem in problems)


def test_empty_recommendation_with_warning_passes():
    item = BY_ID["E001"]
    resp = response([], warnings=["조건을 충족한 후보가 없습니다."])
    assert check_constraints(item, resp) == []


def judged(detail):
    return [*OK_STAGES, {"t": 7.0, "stage": "조건 판정", "status": "completed", "detail": detail}]


def test_passing_count_reads_both_repo_formats():
    assert passing_count(judged("통과 25개 중 2개 추천, 제외 5개")) == 25  # 에이전트
    assert passing_count(judged("통과 28개 중 5개 선택, 제외 2개")) == 28  # 원본
    # 통과 후보 수를 남기기 전의 에이전트 기록과, 조건 판정까지 가지 못한 기록
    assert passing_count(judged("추천 0개, 제외 5개")) is None
    assert passing_count(OK_STAGES) is None


def test_empty_recommendation_with_passing_candidates_fails():
    empty = response([], warnings=["조건을 충족한 후보가 없습니다."])
    problems = check_overlooked_candidates(empty, judged("통과 25개 중 0개 추천, 제외 5개"))
    assert problems == ["통과 후보가 25개인데 추천이 0개다"]

    record = score_case(BY_ID["E031"], empty, judged("통과 25개 중 0개 추천, 제외 5개"))
    assert record["constraints_passed"] is False and record["passed"] is False
    assert record["passing_count"] == 25


def test_empty_recommendation_is_fine_when_nothing_passed_or_count_is_unknown():
    empty = response([], warnings=["조건을 충족한 후보가 없습니다."])
    assert check_overlooked_candidates(empty, judged("통과 0개 중 0개 추천, 제외 30개")) == []
    assert check_overlooked_candidates(empty, judged("추천 0개, 제외 5개")) == []
    # 추천을 냈으면 통과 후보가 더 남아 있어도 문제가 아니다
    some = response([game()])
    assert check_overlooked_candidates(some, judged("통과 25개 중 1개 추천, 제외 5개")) == []


def test_excluded_genre_in_recommendation_fails():
    item = next(entry for entry in DATA if entry["expect"].get("exclude_genres") == ["Horror"])
    problems = check_constraints(item, response([game(themes=["Horror", "Action"])]))
    assert any("Horror" in problem for problem in problems)


def test_excluded_genre_absent_passes():
    item = next(entry for entry in DATA if entry["expect"].get("exclude_genres") == ["Horror"])
    assert check_constraints(item, response([game(genres=["Puzzle"])])) == []


def test_free_requirement_rejects_paid_game():
    item = next(entry for entry in DATA if entry["expect"].get("require_free"))
    problems = check_constraints(item, response([game(price_krw=500)]))
    assert any("무료 조건인데" in problem for problem in problems)


def test_hardware_checked_rejects_skipped_verdict():
    item = next(entry for entry in DATA if entry["expect"].get("hardware_checked"))
    resp = response(
        [game(hardware_status="skipped")],
        conditions={"hardware": HardwareSpecs(gpu="RTX 3060")},
    )
    problems = check_constraints(item, resp)
    assert any("skipped" in problem for problem in problems)


def test_hardware_checked_requires_conditions_hardware():
    item = next(entry for entry in DATA if entry["expect"].get("hardware_checked"))
    problems = check_constraints(item, response([game()]))
    assert any("conditions.hardware가 비었다" in problem for problem in problems)


def test_more_games_than_requested_fails():
    item = next(entry for entry in DATA if entry["expect"].get("max_games") == 1)
    resp = response(
        [game(igdb_id=1), game(igdb_id=2)], conditions={"recommendation_count": 5}
    )
    problems = check_constraints(item, resp)
    assert any("질문의 1개" in problem for problem in problems)


def test_trajectory_happy_path_passes():
    assert check_trajectory(BY_ID["E001"], OK_STAGES) == []


def test_missing_required_stage_fails():
    stages = [event for event in OK_STAGES if event["stage"] != "가격"]
    problems = check_trajectory(BY_ID["E001"], stages)  # E001은 '가격'을 요구한다
    assert any("'가격'" in problem for problem in problems)


def test_failed_stage_fails():
    stages = [*OK_STAGES, {"t": 8.0, "stage": "리뷰 요약", "status": "failed", "detail": None}]
    problems = check_trajectory(BY_ID["E001"], stages)
    assert any("실패한 단계" in problem for problem in problems)


def test_price_before_search_fails():
    stages = [
        {"t": 0.0, "stage": "질문 분해", "status": "started", "detail": None},
        {"t": 1.0, "stage": "질문 분해", "status": "completed", "detail": None},
        {"t": 1.0, "stage": "에이전트 추론", "status": "started", "detail": None},
        {"t": 2.0, "stage": "가격", "status": "started", "detail": None},
        {"t": 3.0, "stage": "가격", "status": "completed", "detail": None},
        {"t": 3.0, "stage": "게임 검색", "status": "started", "detail": None},
        {"t": 4.0, "stage": "게임 검색", "status": "completed", "detail": None},
        {"t": 5.0, "stage": "에이전트 추론", "status": "completed", "detail": None},
    ]
    problems = check_trajectory(BY_ID["E001"], stages)
    assert any("먼저 실행됐다" in problem for problem in problems)


def test_answer_must_mention_every_recommended_game():
    """실측에서 실제 결함을 잡은 검사다. 추천 목록과 답변의 게임 이름이 어긋났다."""
    resp = response(
        [game(igdb_id=1, name="게임 가"), game(igdb_id=2, name="게임 나")],
        answer="게임 가를 추천합니다. 가격이 좋습니다. 재미있습니다.",
    )
    problems = check_answer_format(resp)
    assert any("게임 나" in problem for problem in problems)


def test_answer_with_markdown_fails():
    resp = response([], answer="**굵게**. 두 번째. 세 번째.")
    assert any("마크다운" in problem for problem in check_answer_format(resp))


def test_answer_too_short_fails():
    resp = response([], answer="한 문장뿐입니다.")
    assert any("문장이다" in problem for problem in check_answer_format(resp))


def test_empty_recommendation_may_answer_in_two_sentences():
    # 추천이 없으면 "없다 + 왜 없다" 두 문장을 받는다. 추천이 있으면 여전히 3문장부터다.
    two = "조건에 맞는 게임이 없습니다. 모든 후보가 예산을 넘었습니다."
    assert check_answer_format(response([], answer=two)) == []
    with_game = response([game(1, "Game A")], answer="Game A를 추천합니다. 예산 안입니다.")
    assert any("3~6문장" in problem for problem in check_answer_format(with_game))


def test_rescore_recomputes_only_answer_format():
    two = "조건에 맞는 게임이 없습니다. 모든 후보가 예산을 넘었습니다."
    base = {
        "id": "E1",
        "constraints_passed": True,
        "trajectory_passed": True,
        "answer_format_passed": False,
        "passed": False,
        "answer_format_problems": ["답변이 2문장이다(3~6문장이어야 한다)"],
        "recommended": [],
        "answer": two,
    }
    assert rescore_record(base)["passed"] is True
    # 다른 축이 실패한 문항은 형식이 풀려도 통과가 아니다
    assert rescore_record({**base, "constraints_passed": False})["passed"] is False
    # 추천이 있는 2문장은 여전히 위반이다
    assert rescore_record({**base, "recommended": ["조건"]})["answer_format_passed"] is False
    failed = {"id": "E2", "error": "PipelineStageError: x", "passed": False}
    assert rescore_record(failed) == failed


def test_summary_reports_questions_with_recommendations_separately():
    def record(id_, count, passed, seconds, grounded, passing=None):
        return {
            "id": id_,
            "family": "count",
            "passed": passed,
            "constraints_passed": passed,
            "trajectory_passed": True,
            "answer_format_passed": True,
            "recommended_count": count,
            "passing_count": passing,
            "seconds": seconds,
            "judge": {"grounded_score": grounded, "linked_score": grounded},
        }

    summary = summarize(
        [
            record("E1", 2, True, 12.0, 4),
            record("E2", 3, False, 14.0, 2),
            # 빈 추천은 빨리 끝나고 심판 점수가 만점이라 전체 수치를 끌어올린다
            record("E3", 0, True, 5.0, 5, passing=0),
            record("E4", 0, False, 6.0, 5, passing=25),
            {"id": "E5", "family": "count", "passed": False, "error": "X: y", "seconds": 1.0},
        ]
    )

    assert summary["passed"] == 2 and summary["empty_recommendations"] == 2
    assert summary["overlooked_empty"] == 1
    assert summary["judge"]["grounded_mean"] == 4.0
    assert summary["with_recommendations"] == {
        "scored": 2,
        "passed": 1,
        "latency_median": 14.0,
        "grounded_mean": 3.0,
        "linked_mean": 3.0,
    }


def test_summary_without_recommendations_or_judge():
    summary = summarize(
        [{"id": "E1", "family": "count", "passed": True, "recommended_count": 0, "seconds": 3.0}]
    )
    assert summary["with_recommendations"] == {
        "scored": 0,
        "passed": 0,
        "latency_median": None,
        "grounded_mean": None,
        "linked_mean": None,
    }
    assert summary["overlooked_empty"] == 0


def test_empty_answer_fails():
    assert check_answer_format(response([], answer="   ")) == ["답변이 비었다"]


def test_judge_evidence_contains_only_tool_values():
    """심판에게 정답이나 기대값을 넘기지 않는다."""
    resp = response([game(name="게임 가", price_krw=12000, genres=["Puzzle"])])
    evidence = build_evidence(resp)
    assert "게임 가" in evidence
    assert "12,000원" in evidence
    assert "Puzzle" in evidence
    assert "expect" not in evidence


def test_judge_evidence_for_empty_recommendation():
    resp = response([], warnings=["조건을 충족한 후보가 없습니다."])
    evidence = build_evidence(resp)
    assert "추천된 게임이 없다" in evidence
    assert "조건을 충족한 후보가 없습니다." in evidence


BASELINE_STAGES = [
    {"t": 0.0, "stage": "질문 분해", "status": "started", "detail": None},
    {"t": 1.0, "stage": "질문 분해", "status": "completed", "detail": None},
    {"t": 1.0, "stage": "게임 검색", "status": "started", "detail": None},
    {"t": 2.0, "stage": "게임 검색", "status": "completed", "detail": "후보 30개"},
    {"t": 2.0, "stage": "가격", "status": "started", "detail": None},
    {"t": 3.0, "stage": "가격", "status": "completed", "detail": None},
    {"t": 3.0, "stage": "하드웨어", "status": "started", "detail": None},
    {"t": 4.0, "stage": "하드웨어", "status": "completed", "detail": None},
    {"t": 5.0, "stage": "최종 답변 생성", "status": "started", "detail": None},
    {"t": 6.0, "stage": "최종 답변 생성", "status": "completed", "detail": None},
]


def test_detect_profile_matches_the_repo_layout():
    """평가 코드를 두 저장소에 같은 내용으로 두므로, 프로필을 스스로 맞게 판단해야 한다."""
    profile = detect_profile()
    assert profile in BASE_STAGES
    agent_layer_exists = pathlib.Path(app.__file__).parent.joinpath("agent").is_dir()
    assert profile == ("agent" if agent_layer_exists else "baseline")


def test_two_profiles_expect_different_base_stages():
    assert "에이전트 추론" in BASE_STAGES["agent"]
    assert "최종 답변 생성" in BASE_STAGES["baseline"]
    assert "에이전트 추론" not in BASE_STAGES["baseline"]


def test_baseline_trajectory_passes_on_baseline_profile():
    assert check_trajectory(BY_ID["E001"], BASELINE_STAGES, "baseline") == []


def test_baseline_trajectory_fails_on_agent_profile():
    """프로필을 잘못 주면 공통 단계가 어긋나 실패한다. 실행 시 프로필을 기록해 둔다."""
    problems = check_trajectory(BY_ID["E001"], BASELINE_STAGES, "agent")
    assert any("에이전트 추론" in problem for problem in problems)


def test_agent_trajectory_fails_on_baseline_profile():
    problems = check_trajectory(BY_ID["E001"], OK_STAGES, "baseline")
    assert any("최종 답변 생성" in problem for problem in problems)
