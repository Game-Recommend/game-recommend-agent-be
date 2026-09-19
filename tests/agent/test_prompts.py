import json

from app.agent.prompts import (
    AGENT_SYSTEM,
    build_empty_challenge,
    build_rejection,
    build_user_input,
    describe_conditions,
)
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareSpecs


def make_conditions() -> GameConditions:
    return GameConditions(
        hardware=HardwareSpecs(
            cpu="Ryzen 5 5600X",
            gpu="RTX 3060",
            ram_gb=16,
            os="Windows 11",
            raw_text=(
                "Ryzen 5 5600X, RTX 3060, "
                "시스템 RAM 16GB인 Windows 11 PC"
            ),
        ),
        genres=["Adventure", "Action"],
        excluded_genres=["Horror"],
        preferences=[
            "스토리 중요",
            "Steam 평가 중요",
        ],
        players=2,
        connection="online",
        play_mode="cooperative",
        max_price_krw=30000,
        max_playtime_hours=30,
        max_session_minutes=60,
        platforms=["PC"],
        recommendation_count=5,
    )


def extract_search_arguments(message: str) -> dict:
    json_text = message.split(
        "[search_games 검색 인자(JSON)]\n",
        maxsplit=1,
    )[1].split(
        "\n\n[실행 지시]",
        maxsplit=1,
    )[0]

    return json.loads(json_text)


def test_describe_conditions_contains_all_conditions():
    text = "\n".join(describe_conditions(make_conditions()))

    expected = [
        "CPU Ryzen 5 5600X",
        "GPU RTX 3060",
        "RAM 16GB",
        "OS Windows 11",
        "선호 분류: Adventure, Action",
        "제외 분류: Horror",
        "취향: 스토리 중요, Steam 평가 중요",
        "인원: 2명(사용자 포함)",
        "연결: 온라인",
        "플레이 방식: 협동",
        "예산: 30,000원 이하",
        "전체 완료 시간: 30시간 이하",
        "한 판 시간: 60분 이하",
        "플랫폼: PC",
        "요청 개수: 5개",
    ]

    for value in expected:
        assert value in text


def test_build_user_input_contains_all_sections():
    message = build_user_input(
        "친구 한 명과 온라인 협동 게임을 추천해줘.",
        make_conditions(),
    )

    assert "[사용자 질문]" in message
    assert "친구 한 명과 온라인 협동 게임을 추천해줘." in message
    assert "[추출한 조건]" in message
    assert "[search_games 검색 인자(JSON)]" in message
    assert "[실행 지시]" in message


def test_search_arguments_match_game_search_contract():
    message = build_user_input("질문", make_conditions())
    arguments = extract_search_arguments(message)

    assert arguments == {
        "genres": ["Adventure", "Action"],
        "excluded_genres": ["Horror"],
        "players": 2,
        "connection": "online",
        "play_mode": "cooperative",
        "max_playtime_hours": 30.0,
        "max_session_minutes": 60.0,
        "platforms": ["PC"],
    }


def test_search_arguments_hide_server_managed_values():
    message = build_user_input("질문", make_conditions())
    arguments = extract_search_arguments(message)

    assert "hardware" not in arguments
    assert "max_price_krw" not in arguments
    assert "preferences" not in arguments
    assert "recommendation_count" not in arguments


def test_empty_conditions_are_preserved_without_invention():
    conditions = GameConditions()
    arguments = extract_search_arguments(
        build_user_input("아무 게임이나 추천해줘.", conditions)
    )

    assert arguments == {
        "genres": [],
        "excluded_genres": [],
        "players": None,
        "connection": None,
        "play_mode": None,
        "max_playtime_hours": None,
        "max_session_minutes": None,
        "platforms": [],
    }


def test_zero_budget_is_described_as_free_only():
    conditions = GameConditions(max_price_krw=0)

    text = "\n".join(describe_conditions(conditions))

    assert "예산: 무료 게임만" in text


def test_rejection_contains_all_problems():
    message = build_rejection(
        [
            "추천 개수는 2개 이하여야 합니다 (현재 3개)",
            "Game 1(igdb_id 1)은 추천할 수 없습니다: 가격 미충족",
        ]
    )

    assert "[RecommendationDraft 거부]" in message
    assert "추천 개수는 2개 이하여야 합니다" in message
    assert "Game 1(igdb_id 1)" in message
    assert "가격 미충족" in message
    assert "후보 목록에 없는 igdb_id를 추가하지 마세요" in message
    assert "RecommendationDraft를 다시 제출하세요" in message


def test_agent_system_preserves_code_contracts():
    required_names = {
        "search_games",
        "get_prices",
        "assess_hardware",
        "get_review_scores",
        "summarize_reviews",
        "RecommendationDraft",
        "recommended_igdb_ids",
        "AgentContext.conditions",
    }

    for name in required_names:
        assert name in AGENT_SYSTEM

    normalized_prompt = AGENT_SYSTEM.lower()

    assert "[추출한 조건]" in AGENT_SYSTEM
    assert "[search_games 검색 인자(JSON)]" in AGENT_SYSTEM
    assert "same response turn" in normalized_prompt
    assert "unmet or unknown" in normalized_prompt
    assert "do not repeat the same" in normalized_prompt
    assert '{"error": "..."}' in AGENT_SYSTEM

def test_build_user_input_requires_review_scores_for_selection():
    conditions = GameConditions(
        preferences=["좋은 Steam 평가"],
        recommendation_count=3,
    )

    message = build_user_input(
        "Steam 평가가 좋은 게임 3개 추천해줘.",
        conditions,
    )

    assert "get_review_scores에 한 번만 전달하세요" in message
    assert "wilson_score를 우선 기준" in message
    assert "리뷰 점수를 확인할 수 없는 후보" in message
    assert "summarize_reviews에는 최종 추천 후보" in message

def test_build_user_input_does_not_force_reviews_without_review_criterion():
    conditions = GameConditions(
        genres=["Adventure"],
        recommendation_count=3,
    )

    message = build_user_input(
        "어드벤처 게임 3개 추천해줘.",
        conditions,
    )

    assert "이 요청은 Steam 평가를 추천 기준으로 포함합니다" not in message
    assert "get_review_scores에 한 번만 전달하세요" not in message

def test_build_user_input_states_dynamic_draft_limit():
    conditions = GameConditions(
        genres=["Action"],
        recommendation_count=4,
    )

    message = build_user_input(
        "액션 게임 4개 추천해줘.",
        conditions,
    )

    assert "recommended_igdb_ids" in message
    assert "최대 4개" in message
    assert "전체 후보 수와 최종 추천 수를 혼동하지 마세요" in message

def test_rejection_requires_reducing_excess_candidates():
    message = build_rejection(
        ["추천 개수는 4개 이하여야 합니다 (현재 10개)"]
    )

    assert "요청 개수 이하로 줄이세요" in message
    assert "그대로 다시 제출하지 마세요" in message
    assert "answer의 게임 수와 내용도 함께 수정하세요" in message

def test_empty_hardware_is_normalized_to_none():
    conditions = GameConditions(
        hardware=HardwareSpecs(),
    )

    assert conditions.hardware is None

def test_soft_free_preference_does_not_become_hard_budget():
    conditions = GameConditions(
        preferences=["무료 선호"],
        max_price_krw=0,
    )

    assert conditions.max_price_krw is None

def test_mandatory_free_budget_remains_zero():
    conditions = GameConditions(
        preferences=[],
        max_price_krw=0,
    )

    assert conditions.max_price_krw == 0

def test_build_user_input_explains_soft_free_preference():
    conditions = GameConditions(
        genres=["Role-playing (RPG)"],
        preferences=["무료 선호"],
        max_price_krw=None,
        platforms=["PC"],
        recommendation_count=3,
    )

    message = build_user_input(
        "무료면 좋겠어.",
        conditions,
    )

    assert "필수 가격 조건이 아닙니다" in message
    assert "quote.amount_krw=0" in message
    assert "무료 게임이라고 설명하지 마세요" in message

def test_build_user_input_does_not_assume_multiplayer():
    conditions = GameConditions(
        genres=["Role-playing (RPG)"],
        players=None,
        connection=None,
        play_mode=None,
        platforms=["PC"],
    )

    message = build_user_input(
        "친구들과 PC에서 할 RPG를 찾고 있어.",
        conditions,
    )

    assert "인원, 연결 방식, 플레이 방식은 확정되지 않았습니다" in message
    assert "친구와 함께할 수 있다고 단정하지 마세요" in message

def test_build_user_input_does_not_warn_for_confirmed_multiplayer():
    conditions = GameConditions(
        players=3,
        connection="online",
        play_mode="cooperative",
    )

    message = build_user_input(
        "친구 두 명과 온라인 협동 게임을 찾고 있어.",
        conditions,
    )

    assert "인원, 연결 방식, 플레이 방식은 확정되지 않았습니다" not in message

def test_agent_system_separates_review_score_and_summary():
    normalized = " ".join(AGENT_SYSTEM.split())

    assert "get_review_scores" in normalized
    assert "summarize_reviews" in normalized
    assert "wilson_score as the primary ranking signal" in normalized
    assert "Pass only final selected candidate igdb_ids" in normalized
    assert (
        "must not be used as a substitute for get_review_scores"
        in normalized
    )

def test_user_input_explains_review_tool_roles():
    conditions = GameConditions(
        genres=["Role-playing (RPG)"],
        preferences=["Steam 평가 중요"],
        platforms=["PC"],
        recommendation_count=3,
    )

    message = build_user_input(
        "Steam 평가가 좋은 PC RPG 3개 추천해줘.",
        conditions,
    )

    assert "get_review_scores" in message
    assert "summarize_reviews" in message
    assert "최종 추천 후보" in message

def test_user_input_forbids_score_claims_without_review_criterion():
    conditions = GameConditions(
        genres=["Role-playing (RPG)"],
        platforms=["PC"],
        recommendation_count=3,
    )

    message = build_user_input(
        "PC RPG 3개 추천해줘.",
        conditions,
    )

    assert "get_review_scores를 호출하지 말고" in message
    assert "높은 추천 비율" in message
    assert "정성적 설명에만 사용하세요" in message


def test_build_user_input_includes_dynamic_recommendation_limit():
    conditions = GameConditions(recommendation_count=3)

    message = build_user_input(
        "게임 3개 추천해줘.",
        conditions,
    )

    assert "recommended_igdb_ids는 최대 3개" in message
    assert "제출 직전에 recommended_igdb_ids의 개수를 직접 세어" in message


def test_agent_selects_by_fit_not_by_search_order():
    # 검색 결과는 인기순이다. 그 순서를 그대로 추천하면 질문과 무관하게 같은 게임이 나온다
    assert "preserve the search order" not in AGENT_SYSTEM
    assert "ordered by popularity, not by fit" in AGENT_SYSTEM
    assert "Judge fit only from the" in AGENT_SYSTEM and "summary" in AGENT_SYSTEM
    assert "Prefer variety" in AGENT_SYSTEM


def test_empty_challenge_lists_passing_candidates_and_leaves_an_exit():
    message = build_empty_challenge(
        [GameCandidate(igdb_id=7, name="Game 7"), GameCandidate(igdb_id=9, name="Game 9")],
        recommendation_count=2,
    )

    assert "[빈 RecommendationDraft 재확인]" in message
    assert "통과한 후보가 2개" in message
    assert "Game 7(igdb_id 7)" in message and "Game 9(igdb_id 9)" in message
    # 실측에서 빈 추천을 만든 오독을 직접 짚는다. "통과"라고 쓰면 답변이 검사하지 않은 조건을
    # 충족했다고 말하게 되므로(실측 9/27), 검사하지 않았다는 사실과 답변 금지 표현을 함께 적는다
    assert "검사하지 않았다는" in message and "추천을 막는 사유가 아닙니다" in message
    assert "충족했다거나 확인했다고 쓰지 마세요" in message
    assert "최대 2개" in message
    # 조건에 맞는 후보가 정말 없으면 빈 목록을 다시 낼 수 있다
    assert "빈 목록을 다시 제출" in message
    assert "다음 응답에서는 어떤 Tool도 호출하지 마세요" in message
    assert "검색 순서는 인기순일 뿐" in message
    # 되물은 답변이 게임 이름만 나열한 2문장으로 짧아지는 것을 실측에서 봤다
    assert "3~6문장" in message and "이름을 Tool 결과에 나온 그대로 모두" in message


def test_rejection_forbids_all_tool_retries():
    message = build_rejection(
        ["추천 개수는 3개 이하여야 합니다 (현재 4개)"]
    )

    assert "다음 응답에서는 어떤 Tool도 호출하지 마세요" in message
    assert "search_games, get_prices, assess_hardware" in message
    assert "수정된 RecommendationDraft를 다시 제출하세요" in message
    assert "Tool 호출 없이 한 번만 제출하세요" in message


def test_agent_system_does_not_treat_soft_price_as_budget():
    normalized = " ".join(AGENT_SYSTEM.split())

    assert "If max_price_krw is null" in AGENT_SYSTEM
    assert "not a verified budget constraint" in normalized
    assert "재미를 보장한다" in AGENT_SYSTEM


def test_build_user_input_does_not_claim_budget_when_max_price_is_null():
    conditions = GameConditions(
        preferences=["가격 3만 원대"],
        max_price_krw=None,
    )

    message = build_user_input(
        "가격은 3만 원대였으면 좋겠어.",
        conditions,
    )

    assert "확정된 예산 상한이 없습니다" in message
    assert "'예산 범위 내'" in message
    assert "필수 가격 조건이 아닙니다" in message

def test_agent_system_forbids_duplicate_price_calls():
    normalized = " ".join(AGENT_SYSTEM.split())

    assert "Call get_prices at most once" in AGENT_SYSTEM
    assert "Never emit more than one get_prices call" in AGENT_SYSTEM
    assert "combine all required IDs into one" in normalized
    assert "status=unknown" in AGENT_SYSTEM
    assert "Do not call get_prices again" in AGENT_SYSTEM
    
def test_build_user_input_explains_mandatory_free_price():
    conditions = GameConditions(
        max_price_krw=0,
        recommendation_count=5,
    )

    message = build_user_input(
        "무료 게임만 추천해줘.",
        conditions,
    )

    assert "quote.amount_krw=0" in message
    assert "price status=met" in message
    assert "get_prices를 다시 호출하지 말고" in message
