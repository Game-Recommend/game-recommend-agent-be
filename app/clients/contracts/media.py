from typing import Protocol

from app.schemas.game import GameCandidate
from app.schemas.media import GameMedia


class MediaClient(Protocol):
    async def fetch_media(self, games: list[GameCandidate]) -> list[GameMedia]:
        """후보별 로고·가로 배너·트레일러. 일부만 찾은 게임은 찾은 항목만 채워 반환한다.

        아무것도 못 찾은 게임은 생략해도 된다. 소스 하나의 실패는 게임 단위로 흡수하고,
        나머지 소스로 채운다. 전부 실패한 경우에만 예외로 전달한다.
        """
        ...
