"""최종 답변 프롬프트 구성 검증. 제외 후보·리뷰·미디어가 LLM 입력에 섞이지 않아야 한다."""

from app.pipeline.final_answer.prompts import SUMMARY_MAX_CHARS, build_answer_input
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.common import ConditionCheck
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareResult, HardwareSpecs, RequirementSpec
from app.schemas.media import GameMedia
from app.schemas.price import PriceQuote, PriceResult
from app.schemas.recommendation import EvaluatedGame, RecommendationEvidence
from app.schemas.review import ReviewSummary


def _evaluated(igdb_id: int, name: str, *, price_status="met", hardware_status="met", **game):
    return EvaluatedGame(
        game=GameCandidate(igdb_id=igdb_id, name=name, **game),
        price=PriceResult(
            igdb_id=igdb_id,
            quote=PriceQuote(igdb_id=igdb_id, amount_krw=25000, source_url="https://store/1"),
            check=ConditionCheck(status=price_status, reason="예산 이하"),
        ),
        hardware=HardwareResult(
            igdb_id=igdb_id,
            requirement=RequirementSpec(
                gpu="GTX 1060", ram_gb=8, raw_text="GTX 1060, 8GB", source_url="https://spec/1"
            ),
            check=ConditionCheck(status=hardware_status, reason="GPU·RAM 최소 사양 이상"),
        ),
    )


def _evidence() -> RecommendationEvidence:
    selected = _evaluated(
        1,
        "Selected Game",
        summary="A co-op adventure across a fantasy kingdom.",
        genres=["Adventure"],
        themes=["Fantasy"],
        platforms=["PC (Microsoft Windows)"],
        playtime_hours=12.4,
        steam_app_id=1001,
        source_url="https://www.igdb.com/games/selected",
    )
    selected.review = ReviewSummary(igdb_id=1, summary="리뷰 요약 본문", source_urls=["https://r/1"])
    selected.media = GameMedia(
        igdb_id=1, logo_url="https://cdn/logo.png", hero_url="https://cdn/hero.jpg",
        trailer_youtube_id="TRAILER123",
    )
    excluded = _evaluated(2, "Excluded Game", price_status="unmet", summary="Too expensive.")
    return RecommendationEvidence(
        conditions=GameConditions(
            hardware=HardwareSpecs(gpu="RTX 3060", ram_gb=16),
            genres=["Adventure"],
            excluded_genres=["Horror"],
            players=2,
            connection="online",
            play_mode="cooperative",
            max_price_krw=30000,
            platforms=["PC"],
            recommendation_count=2,
        ),
        games=[selected],
        excluded_games=[excluded],
        warnings=["Selected Game: 리뷰 요약 확인 불가"],
    )


def test_prompt_contains_question_conditions_candidate_and_warnings():
    prompt = build_answer_input("협동 게임 추천", _evidence())

    assert "협동 게임 추천" in prompt
    for expected in (
        "GPU RTX 3060, RAM 16GB", "선호 분류: Adventure", "제외 분류: Horror", "인원: 2명",
        "연결: 온라인", "플레이 방식: 협동", "예산: 30,000원 이하", "플랫폼: PC", "요청 개수: 2개",
    ):
        assert expected in prompt
    assert "[추천 후보 1개]" in prompt
    assert "1. Selected Game" in prompt
    assert "분류: Adventure" in prompt and "테마: Fantasy" in prompt
    assert "전체 완료 시간: 약 12시간" in prompt
    assert "가격: 25,000원 — 충족(예산 이하)" in prompt
    assert "최소 사양: GPU GTX 1060, RAM 8GB — 충족(GPU·RAM 최소 사양 이상)" in prompt
    assert "소개: A co-op adventure across a fantasy kingdom." in prompt
    assert "- Selected Game: 리뷰 요약 확인 불가" in prompt


def test_prompt_omits_excluded_games_reviews_media_urls_and_ids():
    prompt = build_answer_input("협동 게임 추천", _evidence())

    assert "Excluded Game" not in prompt
    assert "Too expensive" not in prompt
    assert "리뷰 요약 본문" not in prompt
    assert "TRAILER123" not in prompt
    assert "https://" not in prompt
    assert "1001" not in prompt  # steam_app_id
    assert "igdb_id" not in prompt


def test_prompt_states_no_candidates_and_default_warning_lines():
    evidence = RecommendationEvidence(conditions=GameConditions())
    prompt = build_answer_input("아무거나", evidence)

    assert "[추천 후보 0개]" in prompt
    assert "모든 조건을 충족한다고 확인된 후보가 없습니다" in prompt
    assert "요청 개수: 3개" in prompt
    assert prompt.rstrip().endswith("[경고]\n- 없음")


def test_prompt_shows_unavailable_price_and_missing_requirement():
    result = _evaluated(3, "Unknown Game", price_status="unknown", hardware_status="skipped")
    result.price.quote = None
    result.hardware.requirement = None
    evidence = RecommendationEvidence(conditions=GameConditions(), games=[result])

    prompt = build_answer_input("질문", evidence)

    assert "가격: 확인 불가 — 확인 불가(예산 이하)" in prompt
    assert "최소 사양: 정보 없음 — 검사 생략" in prompt


def test_prompt_truncates_long_summary():
    result = _evaluated(4, "Long Game", summary="x" * (SUMMARY_MAX_CHARS + 50))
    evidence = RecommendationEvidence(conditions=GameConditions(), games=[result])

    prompt = build_answer_input("질문", evidence)

    assert "x" * SUMMARY_MAX_CHARS + "…" in prompt
    assert "x" * (SUMMARY_MAX_CHARS + 1) not in prompt
