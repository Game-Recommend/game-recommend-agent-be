"""IGDB 담당: 검색 후보 모델."""

from pydantic import BaseModel, Field


class GameCandidate(BaseModel):
    """IGDB 조건을 검증한 후보. 이름 대신 igdb_id로 도구 결과를 연결한다."""

    igdb_id: int = Field(gt=0)
    name: str
    steam_app_id: int | None = Field(default=None, gt=0)
    platforms: list[str] = Field(default_factory=list)
    source_url: str | None = None
