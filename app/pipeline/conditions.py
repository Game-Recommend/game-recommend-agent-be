from pydantic import BaseModel


class GameConditions(BaseModel):
    """질문 가공(1단계)의 출력이자 도구 호출(2단계)의 입력.

    구상의 예상 Input 여섯 가지를 옮긴 초안이다. 질문에 없는 조건은 None이나 빈 목록으로
    둔다 — LLM이 추측해 채우면 사용자가 말하지 않은 조건으로 후보가 걸러진다.
    """

    hardware: str | None = None  # 예: "RTX 3060, RAM 16GB"
    genres: list[str] = []  # 원하는 장르·요소 (예: RPG, 스토리, 협동)
    excluded_genres: list[str] = []  # 피하고 싶은 장르·요소 (예: 공포, 턴제)
    players: int | None = None  # 본인 포함 총인원
    max_price_krw: int | None = None  # 예산 상한 (원)
    max_playtime_hours: float | None = None  # 전체 플레이타임 상한 (시간)
    platforms: list[str] = []  # 예: PC, Mobile
