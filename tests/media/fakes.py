from app.clients.igdb_media import Artwork
from app.clients.steamgriddb import GridAssets
from app.schemas.game import GameCandidate
from app.schemas.media import GameMedia


class FakeMedia:
    """MediaClient 대역. 지정한 게임에만 로고·배너를 채워 돌려준다."""

    def __init__(self, media: list[GameMedia] | None = None, calls: list[str] | None = None,
                 error: Exception | None = None):
        self.media = media or []
        self.calls = calls if calls is not None else []
        self.error = error
        self.requested_ids: list[int] = []

    async def fetch_media(self, games: list[GameCandidate]) -> list[GameMedia]:
        self.calls.append("media")
        self.requested_ids = [game.igdb_id for game in games]
        if self.error is not None:
            raise self.error
        return self.media


class FakeGridDB:
    def __init__(self, assets: dict[int, GridAssets] | None = None, error: Exception | None = None):
        self.assets = assets or {}
        self.error = error
        self.calls = 0

    async def fetch_assets(self, games: list[GameCandidate]) -> dict[int, GridAssets]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return {game.igdb_id: self.assets[game.igdb_id] for game in games
                if game.igdb_id in self.assets}


class FakeIgdbMedia:
    def __init__(self, trailers: dict[int, str] | None = None,
                 artworks: dict[int, Artwork] | None = None, error: Exception | None = None):
        self.trailers = trailers or {}
        self.artworks = artworks or {}
        self.error = error
        self.calls = 0

    async def fetch_trailers(self, igdb_ids: list[int]) -> dict[int, str]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return {i: self.trailers[i] for i in igdb_ids if i in self.trailers}

    async def fetch_hero_artworks(self, igdb_ids: list[int]) -> dict[int, Artwork]:
        if self.error is not None:
            raise self.error
        return {i: self.artworks[i] for i in igdb_ids if i in self.artworks}


class FakeSteamCdn:
    def __init__(self, existing: set[str] | None = None):
        self.existing = existing or set()
        self.checked: list[str] = []

    async def exists(self, url: str) -> bool:
        self.checked.append(url)
        return url in self.existing
