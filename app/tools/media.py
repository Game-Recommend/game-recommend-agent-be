from app.clients.contracts.media import MediaClient
from app.schemas.game import GameCandidate
from app.schemas.media import GameMedia


class MediaTool:
    def __init__(self, client: MediaClient):
        self.client = client

    async def run(self, games: list[GameCandidate]) -> dict[int, GameMedia]:
        """모든 후보에 대해 GameMedia를 돌려준다. 못 찾은 게임은 빈 항목이다."""
        found = {media.igdb_id: media for media in await self.client.fetch_media(games)}
        return {
            game.igdb_id: found.get(game.igdb_id) or GameMedia(igdb_id=game.igdb_id)
            for game in games
        }
