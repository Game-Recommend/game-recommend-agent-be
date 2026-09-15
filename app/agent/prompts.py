"""질문 가공 담당: 에이전트 시스템 프롬프트와 사용자 입력·거부 메시지 구성.

Tool 이름(search_games, get_prices, assess_hardware, summarize_reviews)과 최종 출력 이름
(RecommendationDraft)은 코드와 맞아야 한다. 문구를 고칠 때는 tests/agent와 질문 유형별
Tool 호출 표로 확인한다.
"""

from app.pipeline.query_processing.conditions import GameConditions

CONNECTION_LABELS = {"online": "온라인", "local": "로컬(한 화면)"}
PLAY_MODE_LABELS = {"singleplayer": "싱글", "cooperative": "협동", "competitive": "경쟁"}

AGENT_SYSTEM = """당신은 게임 추천 서비스의 에이전트입니다. 도구를 골라 호출해 근거를 모은 뒤,
사용자 조건에 맞는 게임을 추천합니다. 도구가 돌려준 정보만 근거로 씁니다.

[도구 사용 순서]
1. search_games: 입력의 [추출한 조건]을 그대로 인자로 넘겨 후보를 찾는다.
   조건을 완화하거나 없는 조건을 추가하지 않는다.
   후보가 없으면 다른 조건으로 다시 검색하지 말고 그 사실을 답변에 쓴다.
2. get_prices와 assess_hardware: 후보 전체의 igdb_id를 한 번에 넘긴다. 둘은 같은 턴에 함께 호출한다.
   예산이나 PC 사양 조건이 없어도 답변과 카드에 쓰이므로 호출한다.
   예산·사양 기준값은 서버가 알고 있다.
3. 판정 결과에서 status가 met 또는 skipped인 후보만 남긴다. unmet과 unknown은 추천할 수 없다.
4. summarize_reviews: 최종 추천할 후보에만 호출한다. 게임당 수 초와 비용이 든다.
   사용자가 "평가 좋은 게임"처럼 리뷰를 조건으로 말했으면 통과 후보를 요청 개수보다
   조금 넓게 넣어 비교한 뒤 고른다.
5. RecommendationDraft를 제출한다. recommended_igdb_ids는 추천 순서대로, 요청 개수 이하로 넣는다.

[답변 규칙]
- 후보 목록에 있는 게임만 추천한다. 목록에 없는 게임을 기억에서 꺼내 추가하지 않는다.
- 조건에 맞는 후보가 요청 개수보다 적거나 없으면 그 사실을 먼저 말하고,
  도구가 돌려준 이유만 인용한다.
  조건을 임의로 완화하거나 "대신 이런 게임은 어떠냐"고 제안하지 않는다.
- 가격·사양·플레이 시간은 도구가 돌려준 값만 쓴다. 확인하지 못한 항목은 확인하지 못했다고 쓴다.
- 게임마다 사용자 조건과 연결된 한 줄 이유를 쓴다(예: 예산 이하, 협동 지원, 사양 충족).
- 소개 문구가 영어면 한국어로 풀어 쓴다. 원문을 그대로 옮기지 않는다.
- 한국어로, 마크다운 제목·표·링크 없이 3~6문장의 짧은 문단으로 쓴다.
  게임 이름은 도구가 준 원문 그대로 쓴다.
- 첫 문장은 요청 조건과 찾은 개수를 한 줄로 정리한다. 카드에 로고·배너·리뷰가 따로 표시되므로
  세부 정보를 나열하지 말고 "왜 이 게임들이 조건에 맞는지"를 요약한다.

[실패 처리]
- 도구가 {"error": ...}를 돌려주면 그 정보 없이 진행하고, 답변에 확인하지 못했다고 쓴다.
  같은 호출을 반복하지 않는다.
- 후보 목록에 없는 igdb_id를 넘기지 않는다.
- 제출한 초안이 거부되면 거부 사유를 반영해 다시 제출한다.
"""


def describe_conditions(conditions: GameConditions) -> list[str]:
    """None·빈 목록은 생략한 사용자 조건 설명."""
    lines: list[str] = []
    hardware = conditions.hardware
    if hardware is not None:
        parts = [
            f"{label} {value}"
            for label, value in (
                ("CPU", hardware.cpu),
                ("GPU", hardware.gpu),
                ("RAM", f"{hardware.ram_gb:g}GB" if hardware.ram_gb else None),
                ("OS", hardware.os),
            )
            if value
        ]
        lines.append(f"사용자 PC: {', '.join(parts) if parts else hardware.raw_text or '미상'}")
    if conditions.genres:
        lines.append(f"선호 분류: {', '.join(conditions.genres)}")
    if conditions.excluded_genres:
        lines.append(f"제외 분류: {', '.join(conditions.excluded_genres)}")
    if conditions.preferences:
        lines.append(f"취향: {', '.join(conditions.preferences)}")
    if conditions.players is not None:
        lines.append(f"인원: {conditions.players}명(사용자 포함)")
    if conditions.connection is not None:
        lines.append(f"연결: {CONNECTION_LABELS[conditions.connection]}")
    if conditions.play_mode is not None:
        lines.append(f"플레이 방식: {PLAY_MODE_LABELS[conditions.play_mode]}")
    if conditions.max_price_krw is not None:
        if conditions.max_price_krw == 0:
            lines.append("예산: 무료 게임만")
        else:
            lines.append(f"예산: {conditions.max_price_krw:,}원 이하")
    if conditions.max_playtime_hours is not None:
        lines.append(f"전체 완료 시간: {conditions.max_playtime_hours:g}시간 이하")
    if conditions.max_session_minutes is not None:
        lines.append(f"한 판 시간: {conditions.max_session_minutes:g}분 이하")
    if conditions.platforms:
        lines.append(f"플랫폼: {', '.join(conditions.platforms)}")
    lines.append(f"요청 개수: {conditions.recommendation_count}개")
    return lines


def build_user_input(question: str, conditions: GameConditions) -> str:
    """첫 사용자 메시지.

    질문 분해 결과를 함께 넣어 에이전트가 search_games 인자로 그대로 쓰게 한다.
    """
    return "\n".join(
        [
            "[사용자 질문]",
            question.strip(),
            "",
            "[추출한 조건]",
            *(f"- {line}" for line in describe_conditions(conditions)),
            "",
            "[검색 인자(JSON)]",
            conditions.model_dump_json(
                include={
                    "genres",
                    "excluded_genres",
                    "players",
                    "connection",
                    "play_mode",
                    "max_playtime_hours",
                    "max_session_minutes",
                    "platforms",
                }
            ),
        ]
    )


def build_rejection(problems: list[str]) -> str:
    """러너 후검증에 걸렸을 때 에이전트에 되돌리는 메시지."""
    return "\n".join(
        [
            "다음 문제로 추천을 확정할 수 없습니다. "
            "문제를 해결한 뒤 RecommendationDraft를 다시 제출하세요.",
            *(f"- {problem}" for problem in problems),
        ]
    )
