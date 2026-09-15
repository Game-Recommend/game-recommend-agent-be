"""IGDB 담당: 검색 후보 모델."""

from pydantic import BaseModel, Field


class GameCandidate(BaseModel):
    """IGDB 조건을 검증한 후보. 이름 대신 igdb_id로 도구 결과를 연결한다.

    summary·genres·themes·playtime_hours는 최종 답변 LLM이 추천 이유를 쓰는 재료다.
    IGDB에 없으면 None이나 빈 목록이며, 후속 도구는 이 필드를 판정에 쓰지 않는다.
    """

    igdb_id: int = Field(gt=0)
    name: str
    steam_app_id: int | None = Field(default=None, gt=0)
    platforms: list[str] = Field(default_factory=list)
    source_url: str | None = None
    summary: str | None = None  # IGDB 소개 문구. 대부분 영어다
    genres: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    playtime_hours: float | None = Field(default=None, gt=0)  # IGDB 전체 완료 시간(normally)
