"""최종 답변 LLM의 지시문과 입력 구성.

evidence 전체를 직렬화하지 않는다. 프롬프트에는 사용자 질문, 추출 조건, 추천 후보의 IGDB 정보와
가격·사양 판정, 경고만 넣는다. 제외 후보(excluded_games)는 넣지 않아 LLM이 추천할 여지를 없애고,
리뷰 요약·미디어는 카드 UI가 직접 표시하므로 넣지 않는다.
"""

from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.hardware import RequirementSpec
from app.schemas.recommendation import EvaluatedGame, RecommendationEvidence

# IGDB 소개 문구가 길면 자른다. 답변 재료로는 앞부분이면 충분하다.
SUMMARY_MAX_CHARS = 600

STATUS_LABELS = {"met": "충족", "unmet": "미충족", "unknown": "확인 불가", "skipped": "검사 생략"}
CONNECTION_LABELS = {"online": "온라인", "local": "로컬(한 화면)"}
PLAY_MODE_LABELS = {"singleplayer": "싱글", "cooperative": "협동", "competitive": "경쟁"}

ANSWER_SYSTEM = """당신은 게임 추천 서비스의 최종 답변 작성자입니다.
화면 상단에 놓이는 검색 결과 요약을 씁니다. 답변 아래에는 각 게임의 카드(로고·배너·트레일러·
리뷰 요약)가 따로 표시되므로, 세부 정보를 나열하지 말고 "왜 이 게임들이 조건에 맞는지"를 요약합니다.

입력: 사용자 질문, 질문에서 추출한 조건, 조건을 통과한 추천 후보 목록, 경고 목록.

규칙:
- 추천 후보 목록에 있는 게임만 추천합니다. 목록에 없는 게임을 기억에서 꺼내 추가하지 않습니다.
- 후보가 요청 개수보다 적거나 없으면 그 사실을 먼저 말하고, 경고 목록에 있는 이유만 인용합니다.
  조건을 임의로 완화하거나 "대신 이런 게임은 어떠냐"고 제안하지 않습니다.
- 가격·사양·플레이 시간은 입력에 적힌 값만 씁니다. "확인 불가"인 항목은 확인하지 못했다고 씁니다.
- 게임마다 사용자 조건과 연결된 한 줄 이유를 씁니다(예: 예산 이하, 협동 지원, 사양 충족).
- 소개 문구가 영어면 한국어로 풀어 씁니다. 원문을 그대로 옮기지 않습니다.
- 한국어로, 마크다운 제목·표·링크 없이 3~6문장의 짧은 문단으로 씁니다.
  게임 이름은 입력에 적힌 원문 그대로 씁니다.
- 첫 문장은 요청 조건과 찾은 개수를 한 줄로 정리합니다.
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


def _describe_requirement(spec: RequirementSpec | None) -> str:
    if spec is None:
        return "정보 없음"
    parts = [
        f"{label} {value}"
        for label, value in (
            ("OS", spec.os),
            ("CPU", spec.cpu),
            ("GPU", spec.gpu),
            ("RAM", f"{spec.ram_gb:g}GB" if spec.ram_gb else None),
        )
        if value
    ]
    return ", ".join(parts) if parts else spec.raw_text


def describe_game(index: int, result: EvaluatedGame) -> list[str]:
    """추천 후보 하나. 리뷰·미디어·URL·ID는 넣지 않는다."""
    game = result.game
    lines = [f"{index}. {game.name}"]
    if game.genres:
        lines.append(f"   분류: {', '.join(game.genres)}")
    if game.themes:
        lines.append(f"   테마: {', '.join(game.themes)}")
    if game.platforms:
        lines.append(f"   플랫폼: {', '.join(game.platforms)}")
    if game.playtime_hours is not None:
        lines.append(f"   전체 완료 시간: 약 {game.playtime_hours:.0f}시간")

    price, price_check = result.price, result.price.check
    amount = f"{price.quote.amount_krw:,}원" if price.quote is not None else "확인 불가"
    lines.append(f"   가격: {amount} — {STATUS_LABELS[price_check.status]}({price_check.reason})")

    hardware, hardware_check = result.hardware, result.hardware.check
    lines.append(
        f"   최소 사양: {_describe_requirement(hardware.requirement)}"
        f" — {STATUS_LABELS[hardware_check.status]}({hardware_check.reason})"
    )
    if game.summary:
        summary = game.summary.strip()
        if len(summary) > SUMMARY_MAX_CHARS:
            summary = summary[:SUMMARY_MAX_CHARS].rstrip() + "…"
        lines.append(f"   소개: {summary}")
    return lines


def build_answer_input(question: str, evidence: RecommendationEvidence) -> str:
    """LLM 입력 텍스트. excluded_games·review·media는 의도적으로 제외한다."""
    sections = [
        "[사용자 질문]",
        question.strip(),
        "",
        "[추출한 조건]",
        *(f"- {line}" for line in describe_conditions(evidence.conditions)),
        "",
        f"[추천 후보 {len(evidence.games)}개]",
    ]
    if evidence.games:
        for index, result in enumerate(evidence.games, start=1):
            sections.extend(describe_game(index, result))
    else:
        sections.append("(모든 조건을 충족한다고 확인된 후보가 없습니다)")
    sections.append("")
    sections.append("[경고]")
    if evidence.warnings:
        sections.extend(f"- {warning}" for warning in evidence.warnings)
    else:
        sections.append("- 없음")
    return "\n".join(sections)
