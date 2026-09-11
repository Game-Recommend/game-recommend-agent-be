from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.game import GameCandidate


class FakeCatalog:
    def __init__(self, games: list[GameCandidate], calls: list[str] | None = None):
        self.games = games
        self.calls = calls if calls is not None else []
        self.conditions: GameConditions | None = None

    async def search(self, conditions: GameConditions) -> list[GameCandidate]:
        self.calls.append("search")
        self.conditions = conditions
        return self.games
