"""에이전트의 최종 출력 모델. `create_agent(response_format=...)`로 LLM에 강제한다."""

from pydantic import BaseModel, Field


class RecommendationDraft(BaseModel):
    """에이전트가 마지막에 제출하는 추천 초안. 러너가 CandidateStore로 검증한 뒤 응답으로 만든다."""

    recommended_igdb_ids: list[int] = Field(
        default_factory=list,
        description=(
            "추천할 게임의 igdb_id를 추천 순서대로. search_games 결과에 있고 "
            "get_prices·assess_hardware 판정이 met 또는 skipped인 게임만 넣는다. "
            "요청 개수 이하여야 하며, 조건에 맞는 게임이 없으면 빈 목록을 낸다."
        ),
    )
    answer: str = Field(
        description=(
            "화면 상단에 놓이는 요약 문단. 한국어 3~6문장, 마크다운·표·링크 없이. "
            "첫 문장은 요청 조건과 찾은 개수를 정리하고, 게임마다 사용자 조건과 연결된 "
            "한 줄 이유를 쓴다."
        ),
    )
