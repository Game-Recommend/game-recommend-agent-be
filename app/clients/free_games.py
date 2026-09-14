"""가격·하드웨어 담당: Steam 밖에서 무료로 배포되는 게임의 수동 목록.

LoL·발로란트처럼 자체 런처로만 배포되는 무료 게임은 Steam·CheapShark 어디에도 가격이 없다.
외부 API에 믿을 만한 무료 플래그가 없으므로, 공식 사이트를 근거로 확인한 게임만 여기에 적는다.
추측으로 추가하지 않는다. 항목이 없는 게임은 가격 확인 불가(unknown)로 남는다.

키는 normalize_title()로 정규화한 게임명이다. 값은 근거 링크다.
"""

import re

_NON_ALNUM_RE = re.compile(r"[^0-9a-z가-힣]+")


def normalize_title(title: str) -> str:
    """대소문자·공백·기호 차이를 무시하고 게임명을 비교하기 위한 키."""
    return _NON_ALNUM_RE.sub("", title.lower())


FREE_GAMES: dict[str, str] = {
    normalize_title(name): url
    for name, url in (
        ("League of Legends", "https://www.leagueoflegends.com/"),
        ("Teamfight Tactics", "https://teamfighttactics.leagueoflegends.com/"),
        ("Legends of Runeterra", "https://playruneterra.com/"),
        ("VALORANT", "https://playvalorant.com/"),
        ("Fortnite", "https://www.fortnite.com/"),
        ("Rocket League", "https://www.rocketleague.com/"),
        ("Genshin Impact", "https://genshin.hoyoverse.com/"),
        ("Honkai: Star Rail", "https://hsr.hoyoverse.com/"),
        ("Zenless Zone Zero", "https://zenless.hoyoverse.com/"),
        ("Wuthering Waves", "https://wutheringwaves.kurogames.com/"),
        ("Roblox", "https://www.roblox.com/"),
        ("Hearthstone", "https://hearthstone.blizzard.com/"),
        ("Diablo Immortal", "https://diabloimmortal.blizzard.com/"),
    )
}
