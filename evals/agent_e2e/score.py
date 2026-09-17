"""에이전트 엔드투엔드 채점기.

세 축을 따로 낸다.

1. `constraints` — 사용자가 말한 필수 조건을 추천 결과가 지켰는가. 코드로만 본다.
2. `trajectory` — 필요한 단계가 실제로 실행됐는가. 진행 이벤트로 본다.
3. `answer` — 답변 문단의 형식. 코드로 본다. 내용 품질은 judge.py의 LLM 심판이 본다.

정답 추천 목록이 없으므로 "좋은 추천인가"는 1~3 어디에서도 재지 않는다.
"""

import re

from app.schemas.recommendation import RecommendationResponse

# 프롬프트가 요구하는 답변 형식: 한국어 3~6문장, 마크다운·표·링크 없이
MARKDOWN = re.compile(r"(\*\*)|(^\s*[-*+]\s)|(^\s*#{1,6}\s)|(\|)|(\[.+?\]\(.+?\))", re.MULTILINE)
SENTENCE_END = re.compile(r"[.!?。]\s|[.!?。]$")
HANGUL = re.compile(r"[가-힣]")

# 추천에 들어갈 수 있는 판정 상태. 루트 README의
# "실패나 누락은 필수 조건 통과로 처리하지 않는다"가 unmet·unknown을 막는다.
PASSING = {"met", "skipped"}

# 전 문항 공통으로 실행돼야 하는 단계. 두 저장소의 구조가 달라 프로필로 가른다.
#   agent    = 이 저장소. LLM이 Tool을 골라 부른다(에이전트 추론).
#   baseline = 원본 game-recommend-be. 고정 파이프라인이 단계를 순서대로 돌리고
#              마지막에 답변을 쓴다(최종 답변 생성).
BASE_STAGES = {
    "agent": ("질문 분해", "에이전트 추론", "게임 검색"),
    "baseline": ("질문 분해", "게임 검색", "최종 답변 생성"),
}


def detect_profile() -> str:
    """이 저장소가 에이전트인지 고정 파이프라인인지 본다.

    `app.agent`가 있으면 에이전트 저장소다. 평가 코드를 두 저장소에 같은 내용으로 두고,
    실행할 때 어느 쪽인지 스스로 판단하게 한다.
    """
    try:
        import app.agent  # noqa: F401
    except ImportError:
        return "baseline"
    return "agent"


def count_sentences(text: str) -> int:
    return len([part for part in SENTENCE_END.split(text) if part.strip()])


def check_constraints(item: dict, response: RecommendationResponse) -> list[str]:
    """사용자가 말한 필수 조건을 추천 결과가 지켰는지 본다."""
    problems: list[str] = []
    expect = item["expect"]
    games = response.games

    # 공통: 판정을 통과하지 않은 게임은 추천에 들어갈 수 없다
    for game in games:
        if game.price.check.status not in PASSING:
            problems.append(
                f"{game.game.name}: 가격 판정이 {game.price.check.status}인데 추천됐다"
            )
        if game.hardware.check.status not in PASSING:
            problems.append(
                f"{game.game.name}: 사양 판정이 {game.hardware.check.status}인데 추천됐다"
            )

    # 공통: 같은 게임을 두 번 추천하지 않는다
    ids = [game.game.igdb_id for game in games]
    if len(ids) != len(set(ids)):
        problems.append(f"추천에 중복 igdb_id가 있다: {ids}")

    # 공통: 추천 개수가 파서가 뽑은 상한을 넘지 않는다
    limit = response.conditions.recommendation_count
    if len(games) > limit:
        problems.append(f"추천 {len(games)}개가 상한 {limit}개를 넘었다")

    # 공통: 빈 목록이면 경고가 이유를 설명해야 한다
    if not games and not response.warnings:
        problems.append("추천이 비었는데 경고가 없다")

    # 문항별: 가격 상한
    if (cap := expect.get("max_price_krw")) is not None:
        for game in games:
            quote = game.price.quote
            if quote is None:
                problems.append(f"{game.game.name}: 예산 조건이 있는데 원화 가격이 없다")
            elif quote.amount_krw > cap:
                problems.append(
                    f"{game.game.name}: {quote.amount_krw:,}원이 상한 {cap:,}원을 넘었다"
                )

    # 문항별: 무료 강제
    if expect.get("require_free"):
        for game in games:
            quote = game.price.quote
            if quote is not None and quote.amount_krw != 0:
                problems.append(f"{game.game.name}: 무료 조건인데 {quote.amount_krw:,}원이다")

    # 문항별: 개수 상한(질문에 적힌 수)
    if (max_games := expect.get("max_games")) is not None:
        if len(games) > max_games:
            problems.append(f"추천 {len(games)}개가 질문의 {max_games}개를 넘었다")

    # 문항별: 제외 장르. IGDB의 genres·themes를 함께 본다
    for excluded in expect.get("exclude_genres", []):
        needle = excluded.casefold()
        for game in games:
            labels = [label.casefold() for label in (*game.game.genres, *game.game.themes)]
            if any(needle in label for label in labels):
                problems.append(
                    f"{game.game.name}: 제외 요청한 {excluded}가 장르·테마에 있다"
                )

    # 문항별: 사양 판정이 실제로 이뤄졌는지. 사양을 말한 질문에서 skipped는 판정을 건너뛴 것이다
    if expect.get("hardware_checked"):
        if response.conditions.hardware is None:
            problems.append("사양을 말한 질문인데 conditions.hardware가 비었다")
        for game in games:
            if game.hardware.check.status == "skipped":
                problems.append(f"{game.game.name}: 사양을 말했는데 판정이 skipped다")

    return problems


def check_trajectory(item: dict, stages: list[dict], profile: str = "agent") -> list[str]:
    """필요한 단계가 실행됐는지, 순서가 맞는지 본다."""
    problems: list[str] = []
    started = [event["stage"] for event in stages if event["status"] == "started"]
    completed = {event["stage"] for event in stages if event["status"] == "completed"}
    failed = [event["stage"] for event in stages if event["status"] == "failed"]

    for stage in BASE_STAGES[profile]:
        if stage not in completed:
            problems.append(f"공통 단계 '{stage}'가 완료되지 않았다")
    for stage in item.get("required_stages", []):
        if stage not in completed:
            problems.append(f"이 질문에 필요한 단계 '{stage}'가 완료되지 않았다")
    if failed:
        problems.append(f"실패한 단계가 있다: {', '.join(failed)}")

    # 검색이 가격·사양보다 먼저여야 한다. 후보가 없으면 판정할 대상이 없다.
    if "게임 검색" in started:
        first_search = started.index("게임 검색")
        for stage in ("가격", "하드웨어"):
            if stage in started and started.index(stage) < first_search:
                problems.append(f"'{stage}'가 '게임 검색'보다 먼저 실행됐다")

    return problems


def check_answer_format(response: RecommendationResponse) -> list[str]:
    """답변 문단의 형식. 내용 품질은 LLM 심판이 본다."""
    problems: list[str] = []
    answer = response.answer.strip()
    if not answer:
        return ["답변이 비었다"]
    if not HANGUL.search(answer):
        problems.append("답변에 한국어가 없다")
    if MARKDOWN.search(answer):
        problems.append("답변에 마크다운·표·링크가 있다")
    sentences = count_sentences(answer)
    if not 3 <= sentences <= 6:
        problems.append(f"답변이 {sentences}문장이다(3~6문장이어야 한다)")
    # 추천한 게임은 답변에서 언급돼야 한다
    for game in response.games:
        if game.game.name not in answer:
            problems.append(f"추천한 '{game.game.name}'이 답변에 없다")
    return problems


def score_case(
    item: dict, response: RecommendationResponse, stages: list[dict], profile: str = "agent"
) -> dict:
    constraints = check_constraints(item, response)
    trajectory = check_trajectory(item, stages, profile)
    answer = check_answer_format(response)
    return {
        "id": item["id"],
        "family": item["family"],
        "constraints_passed": not constraints,
        "trajectory_passed": not trajectory,
        "answer_format_passed": not answer,
        "passed": not (constraints or trajectory or answer),
        "constraint_problems": constraints,
        "trajectory_problems": trajectory,
        "answer_format_problems": answer,
        "recommended": [game.game.name for game in response.games],
        "recommended_count": len(response.games),
        "excluded_count": len(response.excluded_games),
        "warnings": response.warnings,
    }
