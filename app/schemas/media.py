"""미디어 담당: 추천 카드용 로고·가로 배너·트레일러 모델."""

from typing import Literal

from pydantic import BaseModel, Field

MediaSource = Literal["steamgriddb", "steam", "igdb"]


class GameMedia(BaseModel):
    """추천 카드 하나를 그리는 데 필요한 미디어. 없는 항목은 None이며 프론트가 텍스트로 대체한다.

    - logo_url: 투명 배경 로고(PNG). 게임 목록에서 이름 대신 놓는다.
    - hero_url: 가로 배너. SteamGridDB 히어로(1920×620·3840×1240) → Steam 라이브러리 히어로 →
      IGDB 가로 아트워크(t_1080p) 순으로 채운다. 크기는 프론트가 자를 때 쓴다.
    - trailer_youtube_id: IGDB game_videos의 YouTube ID. `youtube.com/embed/{id}`로 배너 위에
      얹는다.
      YouTube는 무음일 때만 자동재생되므로 `mute=1`이 필요하다.
    """

    igdb_id: int = Field(gt=0)
    logo_url: str | None = None
    logo_source: MediaSource | None = None
    hero_url: str | None = None
    hero_width: int | None = Field(default=None, gt=0)
    hero_height: int | None = Field(default=None, gt=0)
    hero_source: MediaSource | None = None
    trailer_youtube_id: str | None = None
    trailer_source: MediaSource | None = None
