"""질문 파서 평가셋 200문항. 모델을 호출하거나 모델 출력으로 정답을 만들지 않는다.

정답의 근거는 `app/pipeline/query_processing/prompts.py`의 QUERY_PARSER_SYSTEM이다.
각 문항의 `basis`에 어느 절의 규칙인지 적어, 프롬프트를 고칠 때 어느 문항이 흔들리는지 찾게 한다.

정답은 **부분 정답**이다. `gold`에 적은 필드만 채점하고 적지 않은 필드는 보지 않는다.
`gold`에 명시한 None은 "null이어야 한다"는 주장이고, 키가 없으면 주장하지 않는다.
genres·excluded_genres는 프롬프트가 매핑 예시로 못 박은 10개 카테고리만 쓴다.
preferences는 자유 문장이라 정확 일치 대신 포함(`pref_has`)·불포함(`pref_lacks`) 주장만 한다.
"""

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
cases: list[dict] = []

# 프롬프트 2절이 매핑 예시로 고정한 카테고리 이름. 정답 라벨은 이 안에서만 쓴다.
ACTION = "Action"
ADVENTURE = "Adventure"
ARCADE = "Arcade"
FANTASY = "Fantasy"
HORROR = "Horror"
PARTY = "Party"
PUZZLE = "Puzzle"
RPG = "Role-playing (RPG)"
SCIFI = "Science fiction"
SHOOTER = "Shooter"

# 프롬프트 6절: 개수를 말하지 않으면 5다. conditions.py의 default=3과 다르지만
# 구조화 출력은 필드를 항상 채우므로 실제 계약은 프롬프트 쪽이다(README에 적어 둔다).
DEFAULT_COUNT = 5


def case(
    family, question, gold, basis, *, pref_has=None, pref_lacks=None, pref_nonempty=False, note=None
):
    """문항 하나. gold에 recommendation_count가 없으면 미지정(5)으로 본다."""
    gold = dict(gold)
    gold.setdefault("recommendation_count", DEFAULT_COUNT)
    item = {
        "id": f"Q{len(cases) + 1:03}",
        "family": family,
        "question": question,
        "gold": gold,
        "basis": basis,
    }
    if pref_has:
        item["pref_has"] = pref_has
    if pref_lacks:
        item["pref_lacks"] = pref_lacks
    if pref_nonempty:
        item["pref_nonempty"] = True
    if note:
        item["note"] = note
    cases.append(item)


# ─────────────────────────────────────────────────────────────────────────────
# price: max_price_krw 경계와 모호 표현 (프롬프트 4절)
# ─────────────────────────────────────────────────────────────────────────────
PRICE_EXACT = [
    ("3만 원 이하로 살 수 있는 게임 추천해줘", 30000, "이하 → 그 값 그대로"),
    ("3만 원 미만 게임 추천해줘", 29999, "미만 → 값-1"),
    ("30,000원까지 쓸 수 있어. 게임 추천해줘", 30000, "까지 → 그 값 그대로"),
    ("2만 원 이내로 게임 추천해줘", 20000, "이내 → 그 값 그대로"),
    ("만 원 이하 게임 있어?", 10000, "만 원 = 10000"),
    ("5만 원 이하 게임 추천", 50000, "오만 원 = 50000"),
    ("15,000원 이하 게임 알려줘", 15000, "천 단위 쉼표"),
    ("1만 5천 원 이하 게임", 15000, "만+천 혼합 표기"),
    ("2만 원 미만으로 추천해줘", 19999, "미만 → 값-1"),
    ("20000원 이하 게임", 20000, "쉼표 없는 표기"),
    ("4만원 이하면 좋겠어", 40000, "붙여 쓴 표기"),
    ("천 원 이하 게임 있나", 1000, "천 원 = 1000"),
    ("6만 원까지 괜찮아", 60000, "까지"),
    ("9,900원 이하 게임", 9900, "백 단위"),
    ("3천 원 미만 게임", 2999, "천 단위 미만"),
]
for question, price, why in PRICE_EXACT:
    case(
        "price",
        question,
        {"max_price_krw": price},
        f"4절: {why}",
        # 4절: 필수 가격 조건을 preferences에 복사하지 않는다
        pref_lacks=["원 이하", "원 미만", "원 이내", "원까지", "무료 선호"],
    )

PRICE_FREE_HARD = [
    ("무료 게임만 추천해줘", "무료 게임만 → 0"),
    ("무료 협동 파티 게임만 추천해줘", "'만'이 전체 설명에 걸린다"),
    ("무료로 할 수 있는 RPG만 알려줘", "'만'이 전체 설명에 걸린다"),
    ("돈 안 드는 게임만 찾고 있어", "무료 강제의 다른 표현"),
    ("공짜 게임만 추천해줘", "무료 강제의 다른 표현"),
]
for question, why in PRICE_FREE_HARD:
    gold = {"max_price_krw": 0}
    if "협동 파티" in question:
        gold |= {"genres": [PARTY], "play_mode": "cooperative"}
    if "RPG" in question:
        gold |= {"genres": [RPG]}
    case(
        "price",
        question,
        gold,
        f"4절: {why}. 무료 강제는 preferences에 중복하지 않는다",
        pref_lacks=["무료 선호"],
    )

PRICE_SOFT = [
    "무료면 좋겠다. 게임 추천해줘",
    "가능하면 무료인 게임 알려줘",
    "가급적 무료인 퍼즐 게임 있을까",
    "되도록 무료 게임이면 좋겠어",
]
for question in PRICE_SOFT:
    gold = {"max_price_krw": None}
    if "퍼즐" in question:
        gold |= {"genres": [PUZZLE]}
    case(
        "price",
        question,
        gold,
        "4절: 무료 선호는 soft. max_price_krw를 세우지 않고 preferences로 간다",
        pref_has=["무료 선호"],
    )

PRICE_VAGUE = [
    ("3만 원대 RPG 추천", {"genres": [RPG]}, "3만 원대는 정확한 상한이 아니다"),
    ("적당한 가격의 게임 추천해줘", {}, "'적당한'은 금액이 아니다"),
    ("너무 비싸지 않은 액션 게임", {"genres": [ACTION]}, "'비싸지 않은'은 금액이 아니다"),
    ("싼 게임 추천", {}, "'싼'은 금액이 아니다"),
    ("2만 원대로 살 만한 게임", {}, "만 원대는 정확한 상한이 아니다"),
    ("가성비 좋은 게임 알려줘", {}, "가성비는 금액이 아니다"),
]
for question, extra, why in PRICE_VAGUE:
    case(
        "price",
        question,
        {"max_price_krw": None} | extra,
        f"4절: {why}",
        pref_lacks=["무료 선호"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# time: max_session_minutes와 max_playtime_hours 혼동 (프롬프트 5절)
# 이 계열이 이 서비스의 대표 함정이다. 한 판 길이를 전체 플레이타임에 넣으면 안 된다.
# ─────────────────────────────────────────────────────────────────────────────
SESSION_ONLY = [
    ("한 판이 30분 안 넘는 게임 알려줘", 30, "'한 판'"),
    ("한 번에 30분 정도 할 게임 추천해줘", 30, "'한 번에'"),
    ("한 세션이 1시간 이하인 게임", 60, "'한 세션' + 시간→분 환산"),
    ("한 매치가 20분 이하인 게임 찾아줘", 20, "'한 매치'"),
    ("한 라운드가 15분 안 걸리는 게임", 15, "'한 라운드'"),
    ("한 판에 10분이면 끝나는 게임 추천", 10, "'한 판'"),
    ("앉은 자리에서 40분 안에 끝낼 수 있는 게임", 40, "한 번의 플레이"),
    ("한 경기가 25분 이하인 게임", 25, "'한 경기'"),
    ("한 판당 45분 이하 게임 추천해줘", 45, "'한 판당'"),
    ("짧게 한 판씩 30분 이하로 할 게임", 30, "'한 판씩'"),
]
for question, minutes, why in SESSION_ONLY:
    case(
        "time",
        question,
        # 5절의 핵심: 세션 길이를 max_playtime_hours로 절대 옮기지 않는다
        {"max_session_minutes": float(minutes), "max_playtime_hours": None},
        f"5절: {why} → max_session_minutes 전용, max_playtime_hours는 null",
    )

PLAYTIME_ONLY = [
    ("전체 플레이타임이 15시간 이하인 게임 추천해줘", 15, "'전체 플레이타임'"),
    ("엔딩까지 20시간 안 걸리는 게임", 20, "'엔딩까지'"),
    ("클리어까지 10시간 이하인 게임 알려줘", 10, "'클리어까지'"),
    ("총 플레이타임 30시간 이하 게임", 30, "'총 플레이타임'"),
    ("게임을 끝내는 데 8시간이면 되는 게임", 8, "'끝내는 데'"),
    ("엔딩 보는 데 12시간 이하인 게임 추천", 12, "'엔딩 보는 데'"),
    ("다 깨는 데 25시간 안 넘는 게임", 25, "'다 깨는 데'"),
    ("전체 분량이 5시간 이하인 짧은 게임", 5, "'전체 분량'"),
]
for question, hours, why in PLAYTIME_ONLY:
    case(
        "time",
        question,
        {"max_playtime_hours": float(hours), "max_session_minutes": None},
        f"5절: {why} → max_playtime_hours 전용, max_session_minutes는 null",
    )

BOTH_TIMES = [
    ("엔딩까지 20시간 이하이고 한 번에 30분씩 할 게임", 20, 30),
    ("전체 플레이타임 15시간 이하, 한 판은 1시간 이하인 게임", 15, 60),
    ("클리어까지 10시간이고 한 세션 40분 정도인 게임 추천", 10, 40),
    ("총 30시간 이하이면서 한 판 20분인 게임", 30, 20),
]
for question, hours, minutes in BOTH_TIMES:
    case(
        "time",
        question,
        {"max_playtime_hours": float(hours), "max_session_minutes": float(minutes)},
        "5절: 총 완료 시간과 세션 길이를 모두 말한 경우에만 두 필드를 함께 세운다",
    )

NO_TIME = [
    ("가볍게 할 게임 추천해줘", "'가볍게'는 시간이 아니다"),
    ("짧은 게임 알려줘", "'짧은'은 수치가 아니다"),
    ("시간 많이 안 드는 게임", "수치가 없다"),
]
for question, why in NO_TIME:
    case(
        "time",
        question,
        {"max_playtime_hours": None, "max_session_minutes": None},
        f"5절: {why}. 사용자가 말하지 않은 조건은 만들지 않는다(총칙)",
    )


# ─────────────────────────────────────────────────────────────────────────────
# players: 인원 계산, connection, play_mode (프롬프트 3절)
# ─────────────────────────────────────────────────────────────────────────────
PLAYERS = [
    ("혼자 할 게임 추천해줘", 1, "singleplayer", "'혼자' → 1 + singleplayer"),
    ("친구 한 명과 같이 할 게임", 2, None, "친구 N '과' → N+1"),
    ("친구 두 명과 할 게임 추천해줘", 3, None, "친구 N '과' → N+1"),
    ("친구 네 명과 할 게임", 5, None, "친구 N '과' → N+1"),
    ("친구 네 명이서 같이 할 게임 찾고 있어", 4, None, "친구 N '이서' → N"),
    ("친구 세 명이서 할 게임 알려줘", 3, None, "친구 N '이서' → N"),
    ("둘이서 할 게임 추천", 2, None, "'둘이서' → 2"),
    ("나 혼자 즐길 수 있는 게임", 1, "singleplayer", "'혼자' → 1 + singleplayer"),
    ("셋이서 할 게임 있을까", 3, None, "'셋이서' → 3"),
    ("친구 다섯 명과 할 게임", 6, None, "친구 N '과' → N+1"),
]
for question, players, mode, why in PLAYERS:
    gold = {"players": players}
    if mode:
        gold["play_mode"] = mode
    case(
        "players",
        question,
        gold,
        f"3절: {why}",
        # 3절: 혼자는 players·play_mode 전용이고 preferences에 '혼자 선호'로 중복하지 않는다
        pref_lacks=["혼자 선호"] if players == 1 else None,
    )

PLAYERS_NULL = [
    "친구랑 같이 할 게임 추천해줘",
    "친구들과 할 게임 알려줘",
    "여러 명이서 할 게임 찾아줘",
]
for question in PLAYERS_NULL:
    case(
        "players",
        question,
        {"players": None},
        "3절: 인원을 말하지 않은 '친구랑'·'친구들과'는 players=null",
    )

CONNECTION = [
    ("온라인으로 같이 할 게임 추천해줘", "online", "명시적 온라인"),
    ("온라인 멀티 게임 알려줘", "online", "명시적 온라인"),
    ("한 컴퓨터에서 같이 할 게임", "local", "한 대에서 = local"),
    ("한 화면에서 둘이 할 게임 추천", "local", "한 화면 = local"),
    ("같은 자리에 모여서 할 게임", "local", "모여서 = local"),
]
for question, connection, why in CONNECTION:
    gold = {"connection": connection}
    if "둘이" in question:
        gold["players"] = 2
    case("players", question, gold, f"3절: {why}", pref_lacks=["온라인", "로컬"])

PLAY_MODE = [
    ("협동으로 할 게임 추천해줘", "cooperative", "명시적 협동"),
    ("협력해서 깨는 게임 알려줘", "cooperative", "명시적 협동"),
    ("경쟁하는 게임 추천", "competitive", "명시적 경쟁"),
    ("PvP 게임 알려줘", "competitive", "PvP = competitive"),
    # '대전 게임'은 격투 장르(Fighting)로도 읽히고 프롬프트에 competitive 트리거로
    # 적혀 있지 않다. 계약이 보장하는 표현만 채점한다(REPORT.md의 관찰 2 참고).
    ("서로 경쟁하면서 하는 게임 추천해줘", "competitive", "'경쟁' 명시"),
]
for question, mode, why in PLAY_MODE:
    case("players", question, {"play_mode": mode}, f"3절: {why}")

# 3절: 친구와 함께라고 해서 협동이 되는 것은 아니다
FRIENDS_NOT_COOP = [
    ("친구 한 명과 온라인으로 할 게임 추천해줘", 2, "online"),
    ("친구 두 명과 같이 할 게임 알려줘", 3, None),
    ("친구 세 명이서 온라인으로 할 게임", 3, "online"),
    ("친구랑 온라인으로 할 게임 추천", None, "online"),
]
for question, players, connection in FRIENDS_NOT_COOP:
    case(
        "players",
        question,
        {"players": players, "connection": connection, "play_mode": None},
        "3절: 친구와 함께한다는 말이 협동을 뜻하지 않는다 → play_mode=null",
    )

MODE_COMBO = [
    ("친구 네 명이서 온라인으로 협동하는 게임 찾고 있어", 4, "online", "cooperative"),
    ("친구 한 명과 온라인으로 경쟁하는 게임", 2, "online", "competitive"),
    ("둘이서 한 화면에서 협동하는 게임 추천", 2, "local", "cooperative"),
]
for question, players, connection, mode in MODE_COMBO:
    case(
        "players",
        question,
        {"players": players, "connection": connection, "play_mode": mode},
        "3절: 인원·연결·플레이 방식을 각각 독립으로 채운다",
    )


# ─────────────────────────────────────────────────────────────────────────────
# hardware: 사양 추출과 플랫폼 구분 (프롬프트 1절·6절)
# ─────────────────────────────────────────────────────────────────────────────
HARDWARE_SPECS = [
    ("RTX 3060 쓰는데 할 게임 추천해줘", {"gpu": "RTX 3060"}, "GPU만"),
    ("i5-12400 CPU인데 할 만한 게임", {"cpu": "i5-12400"}, "CPU만"),
    ("RAM 16GB인데 게임 추천해줘", {"ram_gb": 16.0}, "시스템 RAM만"),
    (
        "i5-12400에 RTX 3060, RAM 16GB 쓰고 있어. 게임 추천해줘",
        {"cpu": "i5-12400", "gpu": "RTX 3060", "ram_gb": 16.0},
        "CPU·GPU·RAM 셋 다",
    ),
    ("Ryzen 5 5600 쓰는데 뭐 할까", {"cpu": "Ryzen 5 5600"}, "AMD CPU"),
    ("RX 6600 그래픽카드로 할 게임", {"gpu": "RX 6600"}, "AMD GPU"),
    ("RAM 8기가인데 돌아갈 게임 추천", {"ram_gb": 8.0}, "'기가' 표기"),
    ("GTX 1650, RAM 8GB 노트북이야. 게임 추천해줘", {"gpu": "GTX 1650", "ram_gb": 8.0}, "GPU+RAM"),
    ("Windows 11 쓰는데 게임 추천해줘", {"os": "Windows 11"}, "OS만 (1절: OS만 기록)"),
    ("Windows 10에서 할 게임 알려줘", {"os": "Windows 10"}, "OS만"),
]
for question, specs, why in HARDWARE_SPECS:
    # 1절: 말한 항목만 채우고 나머지는 null이어야 한다
    full = {"cpu": None, "gpu": None, "ram_gb": None, "os": None} | specs
    case("hardware", question, {"hardware": full}, f"1절: {why}")

# 1절: GPU VRAM은 시스템 RAM이 아니다. 이 서비스의 대표 함정.
VRAM_TRAP = [
    ("RTX 3060 8GB VRAM 쓰는데 할만한 게임", "RTX 3060", 8),
    ("RTX 4060 Ti 16GB 그래픽카드인데 게임 추천", "RTX 4060 Ti", 16),
    ("VRAM 12GB인 RTX 3080 쓰고 있어. 게임 추천해줘", "RTX 3080", 12),
    ("그래픽카드 메모리 6GB짜리 GTX 1660 쓰는데", "GTX 1660", 6),
]
for question, gpu, vram in VRAM_TRAP:
    case(
        "hardware",
        question,
        # gpu는 모델명만, ram_gb는 절대 VRAM 용량이 되지 않는다
        {"hardware": {"gpu": gpu, "ram_gb": None}},
        f"1절: VRAM {vram}GB는 hardware.ram_gb가 아니고 gpu는 모델명만 담는다",
    )

# 1절·6절: PC만 말하면 하드웨어가 아니라 플랫폼이다
PLATFORM_ONLY = [
    "PC 게임 추천해줘",
    "컴퓨터로 할 게임 알려줘",
    "노트북으로 할 게임 추천",
    "PC로 할 만한 게임 있어?",
]
for question in PLATFORM_ONLY:
    case(
        "hardware",
        question,
        {"hardware": None, "platforms": ["PC"]},
        "1절·6절: CPU·GPU·RAM·OS 없이 PC만 말하면 hardware=null, platforms=['PC']",
    )

# 1절: 막연한 표현에서 모델명을 지어내지 않는다
NO_INVENT = [
    ("좋은 PC 쓰고 있어. 게임 추천해줘", "'좋은 PC'에서 모델을 지어내지 않는다"),
    ("내장그래픽인데 할 게임 추천해줘", "'내장그래픽'은 모델명이 아니다"),
    ("사양 낮은 컴퓨터로 할 게임", "'사양 낮은'은 모델명이 아니다"),
    ("구형 노트북으로 할 게임 알려줘", "'구형'은 모델명이 아니다"),
    ("고사양 PC로 할 게임 추천", "'고사양'은 모델명이 아니다"),
]
for question, why in NO_INVENT:
    case(
        "hardware",
        question,
        {"hardware": None},
        f"1절: {why}. 사양을 말하지 않았으므로 hardware=null",
    )

# 6절: 플랫폼은 하드웨어와 독립으로 뽑는다. PC라고 말했으면 GPU가 있어도 넣는다
PLATFORM_WITH_SPEC = [
    ("RTX 3060 PC로 할 게임 추천해줘", {"gpu": "RTX 3060"}),
    ("RAM 16GB PC를 쓰고 있어. 게임 추천해줘", {"ram_gb": 16.0}),
    ("i7-13700 PC에서 할 게임 알려줘", {"cpu": "i7-13700"}),
]
for question, specs in PLATFORM_WITH_SPEC:
    case(
        "hardware",
        question,
        {"hardware": specs, "platforms": ["PC"]},
        "6절: PC를 말했으면 하드웨어를 함께 말해도 platforms에 'PC'를 넣는다",
    )

# 1절: hardware.os에 'PC'를 넣지 않는다
case(
    "hardware",
    "윈도우 PC로 할 게임 추천해줘",
    {"platforms": ["PC"]},
    "1절: hardware.os='PC'는 금지. 윈도우는 OS로 인정한다",
    note="hardware.os != 'PC'는 전 문항 공통 불변식으로 채점한다",
)
NO_HARDWARE_AT_ALL = [
    "재미있는 게임 추천해줘",
    "요즘 할 만한 게임 알려줘",
    "게임 하나 추천해줘",
]
for question in NO_HARDWARE_AT_ALL:
    case(
        "hardware",
        question,
        {"hardware": None, "platforms": []},
        "1절: 사양도 OS도 플랫폼도 말하지 않았다 → hardware=null, platforms=[]",
    )


# ─────────────────────────────────────────────────────────────────────────────
# genres: 카테고리 매핑과 긍정·부정 의도 (프롬프트 2절)
# ─────────────────────────────────────────────────────────────────────────────
GENRE_MAP = [
    ("액션 게임 추천해줘", ACTION),
    ("어드벤처 게임 알려줘", ADVENTURE),
    ("슈팅 게임 추천", SHOOTER),
    ("RPG 추천해줘", RPG),
    ("퍼즐 게임 알려줘", PUZZLE),
    ("아케이드 게임 추천해줘", ARCADE),
    ("판타지 게임 추천", FANTASY),
    ("SF 게임 알려줘", SCIFI),
    ("공포 게임 추천해줘", HORROR),
    ("파티 게임 추천해줘", PARTY),
    ("RPG 게임 추천해줘", RPG),
    ("롤플레잉 게임 알려줘", RPG),
]
for question, genre in GENRE_MAP:
    case(
        "genres",
        question,
        {"genres": [genre], "excluded_genres": []},
        "2절: 매핑 예시로 고정된 카테고리 이름을 쓴다",
    )

# 2절: 'RPG를 좋아해'도 genres에 넣는다
GENRE_LIKE = [
    ("RPG를 좋아해. 게임 추천해줘", RPG),
    ("퍼즐 게임 좋아하는데 추천해줘", PUZZLE),
    ("액션을 좋아해. 뭐 할까", ACTION),
]
for question, genre in GENRE_LIKE:
    case(
        "genres",
        question,
        {"genres": [genre], "excluded_genres": []},
        "2절: 좋아한다는 표현도 genres로 간다",
    )

# 2절: 긍정·부정 의도를 섞지 않는다. 제외는 genres에 넣지 않는다
GENRE_EXCLUDE = [
    ("어드벤처 게임 중 공포는 제외해줘", [ADVENTURE], [HORROR]),
    ("액션 슈팅 게임 추천해줘. 공포는 빼고", [ACTION, SHOOTER], [HORROR]),
    ("공포 게임은 싫어. 퍼즐 게임 추천해줘", [PUZZLE], [HORROR]),
    ("RPG 추천해줘. 공포 말고", [RPG], [HORROR]),
    ("파티 게임 좋은데 공포는 안 돼", [PARTY], [HORROR]),
    ("퍼즐이나 아케이드 게임 추천, 액션은 제외", [PUZZLE, ARCADE], [ACTION]),
]
for question, genres, excluded in GENRE_EXCLUDE:
    case(
        "genres",
        question,
        {"genres": genres, "excluded_genres": excluded},
        "2절: 제외 요청을 genres에 넣지 않는다. 복합 요청은 카테고리를 모두 뽑는다",
    )

# 2절: 복합 요청에서 카테고리를 빠뜨리지 않는다
GENRE_COMPOUND = [
    ("액션 어드벤처 게임 추천해줘", [ACTION, ADVENTURE]),
    ("판타지 RPG 알려줘", [FANTASY, RPG]),
    ("SF 슈팅 게임 추천", [SCIFI, SHOOTER]),
    ("공포 어드벤처 게임 좋아해", [HORROR, ADVENTURE]),
]
for question, genres in GENRE_COMPOUND:
    case(
        "genres",
        question,
        {"genres": genres, "excluded_genres": []},
        "2절: 복합 요청의 카테고리를 모두 뽑는다",
    )

# 2절: 게임 카테고리가 아닌 선호는 preferences로 간다
SOFT_PREFERENCE = [
    ("스토리가 중요한 게임 추천해줘", "스토리 중심은 카테고리가 아니다"),
    ("초보자도 할 수 있는 게임 알려줘", "입문 난이도는 카테고리가 아니다"),
    ("Steam 평가 좋은 게임 추천해줘", "평가는 카테고리가 아니다"),
    ("그래픽 예쁜 게임 추천", "그래픽 취향은 카테고리가 아니다"),
    ("한글 지원되는 게임 알려줘", "언어 지원은 카테고리가 아니다"),
]
for question, why in SOFT_PREFERENCE:
    case(
        "genres",
        question,
        {"genres": []},
        f"2절: {why} → preferences로 간다",
        pref_nonempty=True,
    )

# 2절: '턴제 비선호'는 메커니즘 불호이며 excluded_genres에 넣지 않는다
# 소프트 불호("별로야")만 채점한다. 프롬프트 2절이 이 표현을 명시한다.
TURN_BASED_SOFT = [
    "턴제 게임은 별로 안 좋아해. RPG 추천해줘",
    "턴제도 별로야. 액션 게임 알려줘",
]
for question in TURN_BASED_SOFT:
    genre = RPG if "RPG" in question else ACTION
    case(
        "genres",
        question,
        {"genres": [genre]},
        "2절: 턴제 불호는 preferences의 '턴제 비선호'다. "
        "conditions.py의 validator가 excluded_genres의 턴제 필터를 지운다",
        pref_has=["턴제"],
    )

# '턴제 빼고'는 하드 제외 표현이다. 프롬프트 2절의 턴제 규칙은 '별로야' 같은 소프트 불호를
# 겨누므로 하드 제외의 정답을 계약이 정하지 않았다. 카테고리 추출만 채점한다.
case(
    "genres",
    "턴제 빼고 RPG 추천해줘",
    {"genres": [RPG]},
    "2절: 원하는 카테고리 추출만 채점한다. '턴제 빼고'의 저장 위치는 계약 미정",
    note="excluded_genres에 턴제가 들어가는지는 채점하지 않는다(REPORT.md의 관찰 3)",
)

# 2절: 무료 수식어가 카테고리 추출을 막지 않는다
MODIFIER_KEEPS_GENRE = [
    ("무료 협동 파티 게임만", [PARTY], 0),
    ("무료로 할 수 있는 퍼즐 게임만 추천", [PUZZLE], 0),
    ("무료 액션 게임만 알려줘", [ACTION], 0),
]
for question, genres, price in MODIFIER_KEEPS_GENRE:
    case(
        "genres",
        question,
        {"genres": genres, "max_price_krw": price},
        "2절: 수식어가 카테고리 추출을 막지 않는다",
        pref_lacks=["무료 선호"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# count: recommendation_count (프롬프트 6절)
# ─────────────────────────────────────────────────────────────────────────────
COUNT_STATED = [
    ("게임 3개만 추천해줘", 3),
    ("게임 5개 알려줘", 5),
    ("하나만 추천해줘", 1),
    ("10개 추천해줘", 10),
    ("두 개만 알려줘", 2),
    ("일곱 개 추천해줘", 7),
    ("게임 20개 추천", 20),
    ("30개까지 보여줘", 30),
    ("액션 게임 4개 추천해줘", 4),
    ("공포 빼고 게임 6개 알려줘", 6),
]
for question, count in COUNT_STATED:
    gold = {"recommendation_count": count}
    if "액션" in question:
        gold["genres"] = [ACTION]
    if "공포 빼고" in question:
        gold["excluded_genres"] = [HORROR]
    case("count", question, gold, f"6절: 말한 개수 {count}을 그대로 쓴다")

COUNT_UNSTATED = [
    "게임 추천해줘",
    "재미있는 거 알려줘",
    "할 게임 좀 찾아줘",
    "뭐 하면 좋을까",
    "게임 추천 부탁해",
]
for question in COUNT_UNSTATED:
    case(
        "count",
        question,
        # 6절과 conditions.py의 기본값이 모두 5다
        {"recommendation_count": DEFAULT_COUNT},
        f"6절: 개수를 말하지 않으면 {DEFAULT_COUNT}",
    )


# ─────────────────────────────────────────────────────────────────────────────
# no_dup: 전용 필드가 있는 조건을 preferences에 중복하지 않는다 (프롬프트 총칙)
# ─────────────────────────────────────────────────────────────────────────────
NO_DUP = [
    (
        "3만 원 이하 게임 추천해줘",
        {"max_price_krw": 30000},
        ["원 이하", "3만"],
        "가격 상한은 max_price_krw 전용",
    ),
    (
        "혼자 할 게임 추천해줘",
        {"players": 1, "play_mode": "singleplayer"},
        ["혼자"],
        "'혼자'는 players·play_mode 전용",
    ),
    (
        "무료 게임만 추천해줘",
        {"max_price_krw": 0},
        ["무료 선호"],
        "무료 강제는 max_price_krw=0 전용",
    ),
    (
        "온라인으로 할 게임 알려줘",
        {"connection": "online"},
        ["온라인"],
        "온라인은 connection 전용",
    ),
    (
        "협동 게임 추천해줘",
        {"play_mode": "cooperative"},
        ["협동"],
        "협동은 play_mode 전용",
    ),
    (
        "PC 게임 3개 추천해줘",
        {"platforms": ["PC"], "recommendation_count": 3},
        ["PC", "3개"],
        "플랫폼·개수는 전용 필드가 있다",
    ),
    (
        "전체 플레이타임 15시간 이하 게임",
        {"max_playtime_hours": 15.0},
        ["15시간", "플레이타임"],
        "플레이타임은 max_playtime_hours 전용",
    ),
    (
        "한 판 30분 이하 게임 추천",
        {"max_session_minutes": 30.0},
        ["30분", "한 판"],
        "세션 길이는 max_session_minutes 전용",
    ),
    (
        "경쟁 게임 알려줘",
        {"play_mode": "competitive"},
        ["경쟁"],
        "경쟁은 play_mode 전용",
    ),
    (
        "한 화면에서 할 게임 추천",
        {"connection": "local"},
        ["로컬", "한 화면"],
        "로컬은 connection 전용",
    ),
    (
        "2만 원 이하 액션 게임 2개",
        {"max_price_krw": 20000, "genres": [ACTION], "recommendation_count": 2},
        ["원 이하", "2만", "액션"],
        "가격·카테고리·개수 모두 전용 필드가 있다",
    ),
    (
        "친구 한 명과 온라인 협동 게임 3개 추천",
        {
            "players": 2,
            "connection": "online",
            "play_mode": "cooperative",
            "recommendation_count": 3,
        },
        ["온라인", "협동", "3개"],
        "인원·연결·방식·개수 모두 전용 필드가 있다",
    ),
    (
        "공포 제외하고 게임 추천해줘",
        {"excluded_genres": [HORROR]},
        ["공포"],
        "제외 카테고리는 excluded_genres 전용",
    ),
    (
        "Windows 11에서 할 게임",
        {"hardware": {"os": "Windows 11"}},
        ["Windows", "윈도우"],
        "OS는 hardware.os 전용",
    ),
]
for question, gold, lacks, why in NO_DUP:
    case("no_dup", question, gold, f"총칙: {why}. preferences에 중복하지 않는다", pref_lacks=lacks)


# ─────────────────────────────────────────────────────────────────────────────
# combined: 실제 사용자 질문에 가까운 복합 조건. 루트 README의 예상 질문을 포함한다
# ─────────────────────────────────────────────────────────────────────────────
case(
    "combined",
    "내 노트북이 i5-1240P, RAM 16GB, 내장그래픽인데 원활하게 할 수 있는 게임 중에서 "
    "평점 좋은 게임 추천해줘.",
    # 1절: '내장그래픽'에서 GPU 모델을 지어내지 않는다
    {"hardware": {"cpu": "i5-1240P", "ram_gb": 16.0, "gpu": None}},
    "README 예상 질문(하드웨어). 1절: 내장그래픽은 모델명이 아니다",
    pref_nonempty=True,
)
case(
    "combined",
    "친구 4명이서 온라인으로 같이 할 게임을 찾고 있어. 경쟁보다는 협동 위주였으면 좋겠고 "
    "한 판이 너무 길지 않았으면 좋겠어.",
    {
        "players": 4,
        "connection": "online",
        "play_mode": "cooperative",
        # '너무 길지 않게'는 수치가 아니다
        "max_session_minutes": None,
        "max_playtime_hours": None,
    },
    "README 예상 질문(멀티플레이). 3절: 'N명이서'는 N. 5절: 수치 없는 길이는 null",
)
case(
    "combined",
    "지금 2만 원 이하로 살 수 있는 게임 중에서 스토리가 중요한 RPG 추천해줘. "
    "턴제 게임은 별로 안 좋아해.",
    {"max_price_krw": 20000, "genres": [RPG]},
    "README 예상 질문(가격+취향). 2절: 턴제 불호는 preferences",
    pref_has=["턴제"],
    pref_lacks=["원 이하", "무료 선호"],
)
case(
    "combined",
    "취업 준비하면서 가볍게 할 게임을 찾고 있어. 한 번에 30분~1시간 정도 하기 좋고, "
    "전체 플레이타임도 15시간을 넘지 않는 싱글 게임이면 좋겠어.",
    {
        "max_session_minutes": 60.0,
        "max_playtime_hours": 15.0,
        "play_mode": "singleplayer",
    },
    "README 예상 질문(플레이타임+장르). 5절: 세션과 총 시간을 각각 채운다",
)
case(
    "combined",
    "RTX 3060, RAM 16GB PC를 사용하고 있어. 친구 한 명과 온라인으로 같이 할 수 있고, "
    "공포 게임은 싫어. 3만 원 이하이면서 Steam 평가가 좋은 게임 3개만 추천해줘.",
    {
        "hardware": {"gpu": "RTX 3060", "ram_gb": 16.0},
        "platforms": ["PC"],
        "players": 2,
        "connection": "online",
        "excluded_genres": [HORROR],
        "max_price_krw": 30000,
        "recommendation_count": 3,
    },
    "README 예상 질문(복합, 데모용). 모든 절이 함께 걸린다",
    pref_lacks=["원 이하", "무료 선호", "온라인"],
)

COMBINED_MORE = [
    (
        "RTX 4060으로 할 3만 원 이하 액션 게임 3개 추천해줘",
        {
            "hardware": {"gpu": "RTX 4060"},
            "max_price_krw": 30000,
            "genres": [ACTION],
            "recommendation_count": 3,
        },
    ),
    (
        "혼자 할 수 있는 엔딩까지 10시간 이하 어드벤처 게임 2개",
        {
            "players": 1,
            "play_mode": "singleplayer",
            "max_playtime_hours": 10.0,
            "genres": [ADVENTURE],
            "recommendation_count": 2,
        },
    ),
    (
        "친구 세 명이서 한 화면에서 할 무료 파티 게임만 알려줘",
        {
            "players": 3,
            "connection": "local",
            "max_price_krw": 0,
            "genres": [PARTY],
        },
    ),
    (
        "i5-12400, RAM 8GB인데 2만 원 이하 퍼즐 게임 5개 추천",
        {
            "hardware": {"cpu": "i5-12400", "ram_gb": 8.0},
            "max_price_krw": 20000,
            "genres": [PUZZLE],
            "recommendation_count": 5,
        },
    ),
    (
        "온라인으로 친구 네 명과 경쟁하는 슈팅 게임 4개 추천해줘",
        {
            "players": 5,
            "connection": "online",
            "play_mode": "competitive",
            "genres": [SHOOTER],
            "recommendation_count": 4,
        },
    ),
    (
        "한 판 20분 이하인 무료 아케이드 게임만 추천",
        {"max_session_minutes": 20.0, "max_price_krw": 0, "genres": [ARCADE]},
    ),
    (
        "Windows 11에서 할 판타지 RPG 중 공포는 빼고 3개",
        {
            "hardware": {"os": "Windows 11"},
            "genres": [FANTASY, RPG],
            "excluded_genres": [HORROR],
            "recommendation_count": 3,
        },
    ),
    (
        "RTX 3070 8GB VRAM PC로 할 1만 원 이하 SF 게임",
        {
            "hardware": {"gpu": "RTX 3070", "ram_gb": None},
            "platforms": ["PC"],
            "max_price_krw": 10000,
            "genres": [SCIFI],
        },
    ),
    (
        "둘이서 온라인 협동하는 클리어까지 20시간 이하 게임 2개",
        {
            "players": 2,
            "connection": "online",
            "play_mode": "cooperative",
            "max_playtime_hours": 20.0,
            "recommendation_count": 2,
        },
    ),
    (
        "가급적 무료인 혼자 할 퍼즐 게임 알려줘",
        {
            "max_price_krw": None,
            "players": 1,
            "play_mode": "singleplayer",
            "genres": [PUZZLE],
        },
    ),
    (
        "RAM 16GB 노트북으로 할 5만 원 이하 액션 어드벤처 게임 3개",
        {
            "hardware": {"ram_gb": 16.0},
            "max_price_krw": 50000,
            "genres": [ACTION, ADVENTURE],
            "recommendation_count": 3,
        },
    ),
    (
        "친구랑 온라인으로 할 3만 원 미만 게임 추천해줘",
        {"players": None, "connection": "online", "max_price_krw": 29999},
    ),
    (
        "전체 플레이타임 8시간 이하, 한 판 30분 이하인 무료 게임만 5개",
        {
            "max_playtime_hours": 8.0,
            "max_session_minutes": 30.0,
            "max_price_krw": 0,
            "recommendation_count": 5,
        },
    ),
    (
        "내장그래픽 노트북인데 무료로 할 수 있는 퍼즐 게임만 추천",
        {"hardware": None, "max_price_krw": 0, "genres": [PUZZLE]},
    ),
    (
        "Ryzen 5 5600, RX 6600, RAM 16GB PC로 할 공포 게임 2개",
        {
            "hardware": {"cpu": "Ryzen 5 5600", "gpu": "RX 6600", "ram_gb": 16.0},
            "platforms": ["PC"],
            "genres": [HORROR],
            "recommendation_count": 2,
        },
    ),
]
for question, gold in COMBINED_MORE:
    case(
        "combined",
        question,
        gold,
        "복합 조건: 여러 절이 동시에 걸린다",
        pref_lacks=["원 이하", "원 미만"] if gold.get("max_price_krw") else None,
    )


FAMILIES = [
    ("price", "max_price_krw 경계, 무료 강제와 무료 선호, 모호 표현"),
    ("time", "세션 길이와 총 플레이타임 혼동"),
    ("players", "인원 계산, connection, play_mode"),
    ("hardware", "사양 추출, VRAM 함정, PC는 플랫폼"),
    ("genres", "카테고리 매핑, 긍정·부정 의도 분리"),
    ("count", "recommendation_count"),
    ("no_dup", "전용 필드가 있는 조건의 preferences 중복"),
    ("combined", "실제 사용자 질문에 가까운 복합 조건"),
]


def main() -> None:
    counts = Counter(item["family"] for item in cases)
    unknown = set(counts) - {name for name, _ in FAMILIES}
    if unknown:
        raise SystemExit(f"FAMILIES에 없는 계열: {sorted(unknown)}")

    (ROOT / "dataset.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# 질문 파서 평가 문항",
        "",
        f"총 {len(cases)}문항. [build_dataset.py](build_dataset.py)가 만들고 "
        "[dataset.json](dataset.json)이 실행 데이터다.",
        "정답의 근거는 `app/pipeline/query_processing/prompts.py`의 QUERY_PARSER_SYSTEM이며,",
        "문항마다 어느 절의 규칙인지 `basis`에 적었다.",
        "",
        "| 계열 | 문항 수 | 무엇을 보는가 |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {name} | {counts[name]} | {what} |" for name, what in FAMILIES]
    lines += ["", "## 문항", ""]
    for item in cases:
        lines.append(f"- **{item['id']}** ({item['family']}): \"{item['question']}\"")
        lines.append(f"  - 근거: {item['basis']}")
    (ROOT / "questions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"문항 {len(cases)}개")
    for name, _ in FAMILIES:
        print(f"  {name}: {counts[name]}")


if __name__ == "__main__":
    main()
