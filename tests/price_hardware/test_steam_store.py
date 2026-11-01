"""Steam appdetails 응답 변환과 가격·사양 판정. 실제 호출 없이 MockTransport로 검증한다."""

import asyncio
import json

import httpx2
import pytest

from app.clients.steam_store import (
    AppDetails,
    SteamStoreClient,
    choose_app_id,
    parse_app_details,
    parse_requirements,
)
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs
from app.schemas.price import PriceQuote, PriceUnavailable
from tests.price_hardware.fakes import FakeSpecJudge

MINIMUM_HTML = (
    '<strong>Minimum:</strong><br><ul class="bb_ul">'
    "<li><strong>OS *:</strong> Windows 10 64-bit<br></li>"
    "<li><strong>Processor:</strong> Intel Core i5-4460 / AMD FX-6300<br></li>"
    "<li><strong>Memory:</strong> 8 GB RAM<br></li>"
    "<li><strong>Graphics:</strong> NVIDIA GeForce GTX 960 or AMD Radeon R7 370<br></li>"
    "<li><strong>DirectX:</strong> Version 11<br></li>"
    "<li><strong>Storage:</strong> 20 GB available space<br></li></ul>"
)


RECOMMENDED_HTML = (
    '<strong>Recommended:</strong><br><ul class="bb_ul">'
    "<li><strong>Memory:</strong> 16 GB RAM<br></li>"
    "<li><strong>Graphics:</strong> NVIDIA GeForce RTX 2060<br></li></ul>"
)


def app_data(**overrides):
    data = {
        "type": "game",
        "is_free": False,
        "price_overview": {"currency": "KRW", "initial": 3300000, "final": 2700000},
        "packages": [1],
        "release_date": {"coming_soon": False},
        "pc_requirements": {"minimum": MINIMUM_HTML, "recommended": RECOMMENDED_HTML},
    }
    data.update(overrides)
    return {"success": True, "data": data}


def make_client(responses: dict[int, dict], judge=None, calls=None):
    calls = calls if calls is not None else []

    def handler(request: httpx2.Request) -> httpx2.Response:
        app_id = int(request.url.params["appids"])
        calls.append((app_id, request.url.params["cc"], request.url.params["l"]))
        return httpx2.Response(200, content=json.dumps({str(app_id): responses[app_id]}))

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return SteamStoreClient(http, judge or FakeSpecJudge()), calls


def game(igdb_id: int, app_id: int | None = None) -> GameCandidate:
    return GameCandidate(igdb_id=igdb_id, name=f"게임{igdb_id}", steam_app_id=app_id)


def test_parse_requirements_extracts_labeled_fields():
    spec = parse_requirements(MINIMUM_HTML)
    assert spec is not None
    assert spec.os == "Windows 10 64-bit"
    assert spec.cpu == "Intel Core i5-4460 / AMD FX-6300"
    assert spec.gpu == "NVIDIA GeForce GTX 960 or AMD Radeon R7 370"
    assert spec.ram_gb == 8
    assert "DirectX" not in (spec.gpu or "")


def test_parse_requirements_handles_inline_text_and_megabytes():
    spec = parse_requirements(
        "<strong>Minimum:</strong> OS: Windows XP, Memory: 512 MB, Graphics: DirectX 9"
    )
    assert spec is not None
    assert spec.ram_gb == 0.5
    assert spec.gpu == "DirectX 9"
    assert parse_requirements("<strong>Minimum:</strong><br>") is None


def test_prices_are_converted_and_unavailable_reasons_are_distinguished():
    client, calls = make_client(
        {
            1: app_data(),
            2: app_data(is_free=True, price_overview=None),
            3: {"success": False},
            4: app_data(price_overview=None, release_date={"coming_soon": True}),
            5: app_data(price_overview=None, packages=[]),
            6: app_data(price_overview=None),  # 번들 전용 → 생략(unknown)
            7: app_data(price_overview={"currency": "USD", "final": 1999}),
        }
    )
    games = [game(i, i) for i in range(1, 8)] + [game(8)]
    results = {r.igdb_id: r for r in asyncio.run(client.fetch_prices(games))}

    assert results[1] == PriceQuote(
        igdb_id=1, amount_krw=27000, source_url="https://store.steampowered.com/app/1"
    )
    assert results[2].amount_krw == 0
    assert results[3] == PriceUnavailable(igdb_id=3, reason="한국 스토어 미판매")
    assert results[4].reason == "미출시"
    assert results[5].reason == "현재 Steam에서 구매 불가"
    assert 6 not in results
    assert 7 not in results  # USD는 원화로 취급하지 않는다
    assert 8 not in results  # steam_app_id 없음
    assert all(cc == "kr" and lang == "english" for _, cc, lang in calls)


def test_price_and_hardware_share_one_request_per_app():
    client, calls = make_client({10: app_data()})
    games = [game(1, 10)]

    async def both():
        return await asyncio.gather(
            client.fetch_prices(games), client.assess(games, HardwareSpecs(ram_gb=16))
        )

    asyncio.run(both())
    asyncio.run(client.fetch_prices(games))
    assert [app_id for app_id, _, _ in calls] == [10]


def test_memory_rule_decides_before_judge_and_judge_only_sees_gpu_cases():
    judge = FakeSpecJudge(
        verdicts=[HardwareAssessment(igdb_id=1, status="met", reason="RTX 3060 ≥ GTX 960")]
    )
    client, _ = make_client(
        {
            1: app_data(),
            2: app_data(),
            3: app_data(pc_requirements=[]),
            4: app_data(pc_requirements={"minimum": "<strong>Minimum:</strong> Memory: 4 GB RAM"}),
        },
        judge=judge,
    )
    games = [game(1, 1), game(2, 2), game(3, 3), game(4, 4)]

    low_ram = asyncio.run(client.assess(games, HardwareSpecs(gpu="RTX 3060", ram_gb=4)))
    by_id = {a.igdb_id: a for a in low_ram}
    assert by_id[1].status == "unmet"
    assert by_id[1].reason == "메모리 부족: 최소 8 GB, 보유 4 GB"
    assert by_id[3].status == "unknown" and by_id[3].reason == "요구 사양 정보 없음"
    assert by_id[4].status == "unknown"
    assert by_id[4].reason == "비교할 공통 GPU·CPU 항목 없음"
    assert judge.requests == []  # 메모리로 이미 확정된 게임은 판정기에 보내지 않는다

    enough_ram = asyncio.run(client.assess(games, HardwareSpecs(gpu="RTX 3060", ram_gb=16)))
    by_id = {a.igdb_id: a for a in enough_ram}
    assert [r.igdb_id for r in judge.requests] == [1, 2]
    assert judge.requests[0].requirement.gpu == "NVIDIA GeForce GTX 960 or AMD Radeon R7 370"
    assert judge.requests[0].components == ["gpu"]  # 사용자가 CPU를 말하지 않아 GPU만 비교
    assert by_id[1].status == "met"
    assert by_id[2].status == "unknown" and by_id[2].reason == "GPU·CPU 판정 실패"
    assert by_id[1].requirement is not None and by_id[2].requirement is not None
    assert by_id[1].recommended is not None and by_id[2].recommended is not None


def test_ram_only_user_is_judged_by_memory_rule_alone():
    judge = FakeSpecJudge()
    client, _ = make_client({1: app_data()}, judge=judge)
    result = asyncio.run(client.assess([game(1, 1)], HardwareSpecs(ram_gb=16)))
    assert result[0].status == "met"
    assert result[0].reason == "메모리 충족: 최소 8 GB"
    assert result[0].requirement is not None and result[0].requirement.ram_gb == 8
    assert result[0].recommended is not None
    assert result[0].recommended.gpu == "NVIDIA GeForce RTX 2060"
    assert result[0].recommended.ram_gb == 16
    assert judge.requests == []


def test_no_user_specs_returns_requirements_without_judging():
    judge = FakeSpecJudge()
    client, _ = make_client({1: app_data(), 2: app_data(pc_requirements=[])}, judge=judge)
    result = {a.igdb_id: a for a in asyncio.run(client.assess([game(1, 1), game(2, 2)], None))}
    assert result[1].status == "skipped"
    assert result[1].requirement is not None
    assert result[1].requirement.gpu == "NVIDIA GeForce GTX 960 or AMD Radeon R7 370"
    assert result[1].recommended is not None and result[1].recommended.ram_gb == 16
    assert result[2].status == "skipped"
    assert result[2].requirement is None
    assert judge.requests == []


def test_judge_failure_keeps_rule_based_results():
    judge = FakeSpecJudge(error=RuntimeError("LLM down"))
    client, _ = make_client({1: app_data(), 2: app_data()}, judge=judge)
    games = [game(1, 1), game(2, 2)]
    result = asyncio.run(client.assess(games, HardwareSpecs(gpu="RTX 3060", ram_gb=16)))
    assert {a.status for a in result} == {"unknown"}
    assert all(a.reason == "GPU·CPU 판정 실패" for a in result)


def test_http_error_propagates():
    def handler(request):
        return httpx2.Response(429)

    client = SteamStoreClient(
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), FakeSpecJudge()
    )
    with pytest.raises(httpx2.HTTPStatusError):
        asyncio.run(client.fetch_prices([game(1, 1)]))


@pytest.mark.parametrize(
    ("hardware", "reason"),
    [
        (
            HardwareSpecs(gpu="내장그래픽", ram_gb=16),
            "GPU 모델 확인 필요 (예: Iris Xe, Radeon 780M)",
        ),
        (HardwareSpecs(gpu="GeForce"), "GPU 모델 확인 필요 (예: Iris Xe, Radeon 780M)"),
        (HardwareSpecs(cpu="i5", gpu="RTX 3060"), "CPU 모델 확인 필요 (예: i5-12400)"),
        (HardwareSpecs(gpu="ZetaPixel Q999"), "GPU 모델 확인 필요 (예: Iris Xe, Radeon 780M)"),
        (HardwareSpecs(cpu="FictionCore X123"), "CPU 모델 확인 필요 (예: i5-12400)"),
        (HardwareSpecs(cpu="Apple M2"), "Mac 사양 판정 미지원"),
        (HardwareSpecs(gpu="M1 Pro"), "Mac 사양 판정 미지원"),
    ],
)
def test_ambiguous_user_specs_are_skipped_with_requirements_and_no_judge(hardware, reason):
    judge = FakeSpecJudge()
    client, _ = make_client({1: app_data()}, judge=judge)
    result = asyncio.run(client.assess([game(1, 1)], hardware))
    assert result[0].status == "skipped"
    assert result[0].reason == reason
    assert result[0].requirement is not None and result[0].recommended is not None
    assert judge.requests == []


@pytest.mark.parametrize(
    "hardware",
    [
        HardwareSpecs(gpu="Intel Iris Xe"),
        HardwareSpecs(gpu="Radeon 780M"),
        HardwareSpecs(gpu="UHD 630"),
        HardwareSpecs(gpu="RTX 3060 Laptop"),
        HardwareSpecs(gpu="AMD Radeon RX 6600"),
        HardwareSpecs(gpu="GTX 1060 3GB"),
        HardwareSpecs(cpu="Intel Core i5-12400"),
        HardwareSpecs(cpu="i5-1240P"),
        HardwareSpecs(cpu="AMD Ryzen 5 5600"),
        HardwareSpecs(cpu="Core 2 Duo E8400"),
        HardwareSpecs(cpu="라이젠5 5600"),
        HardwareSpecs(gpu="지포스 RTX3060"),
    ],
)
def test_recognized_models_are_sent_to_judge(hardware):
    judge = FakeSpecJudge()
    client, _ = make_client({1: app_data()}, judge=judge)
    asyncio.run(client.assess([game(1, 1)], hardware))
    assert len(judge.requests) == 1


def test_memory_shortfall_beats_ambiguous_gpu():
    client, _ = make_client({1: app_data()})
    result = asyncio.run(client.assess([game(1, 1)], HardwareSpecs(gpu="내장그래픽", ram_gb=4)))
    assert result[0].status == "unmet"


def test_parse_requirements_accepts_alternate_labels():
    # 개발사 원문을 그대로 실은 출처(원신 형식). Steam 라벨과 다르게 표기된 항목도 같은 키로 읽는다.
    spec = parse_requirements(
        "Minimum:\n\nOperating system: Windows 10 64-bit\n\nProcessor: Intel Core i5 or equivalent"
        "\n\nMemory: 8 GB RAM\n\nGraphics card: NVIDIA® GeForce® GT 1030 and higher"
        "\n\nDirectX version: 11\n\nStorage: 30 GB of space"
    )
    assert spec is not None
    assert spec.os == "Windows 10 64-bit"
    assert spec.cpu == "Intel Core i5 or equivalent"
    assert spec.ram_gb == 8
    assert spec.gpu == "NVIDIA® GeForce® GT 1030 and higher"

    spec = parse_requirements("CPU: Ryzen 5 3600, RAM: 16 GB, GPU: RTX 2060, Video Memory: 6 GB")
    assert spec is not None
    assert (spec.cpu, spec.ram_gb, spec.gpu) == ("Ryzen 5 3600", 16, "RTX 2060")
    # "macOS:"처럼 다른 단어에 붙은 "OS"는 라벨로 보지 않는다
    assert parse_requirements("Notes: macOS: not supported") is None


def test_reasons_follow_the_request_language():
    judge = FakeSpecJudge()
    client, _ = make_client(
        {
            1: app_data(),
            3: {"success": False},
            4: app_data(price_overview=None, release_date={"coming_soon": True}),
            5: app_data(price_overview=None, packages=[]),
        },
        judge=judge,
    )

    prices = asyncio.run(client.fetch_prices([game(i, i) for i in (3, 4, 5)], language="en"))
    low_ram = asyncio.run(
        client.assess([game(1, 1)], HardwareSpecs(gpu="RTX 3060", ram_gb=4), language="en")
    )
    judged = asyncio.run(
        client.assess([game(1, 1)], HardwareSpecs(gpu="RTX 3060", ram_gb=16), language="en")
    )

    assert [p.reason for p in prices] == [
        "Not sold in the Korean store",
        "Not yet released",
        "Not currently purchasable on Steam",
    ]
    assert low_ram[0].reason == "Not enough memory: minimum 8 GB, you have 4 GB"
    assert judged[0].reason == "GPU/CPU check failed"  # 대역 판정기가 결과를 내지 않았다
    # GPU·CPU 판정기는 note를 같은 언어로 쓰도록 language를 받는다
    assert judge.language == "en"


# ---------- IGDB가 Steam 앱을 여럿 연결한 게임 ----------
# 값은 2026-11-01 한국 스토어 실제 응답을 줄인 것이다.


def details(app_id, *, price=None, free=False, forwarded_to=None, app_type="game"):
    return AppDetails(
        app_id=app_id,
        available=True,
        app_type=app_type,
        forwarded_to=forwarded_to,
        is_free=free,
        price_krw=price,
    )


def missing(app_id):
    return AppDetails(app_id=app_id, available=False)


def test_parse_keeps_app_type_and_forwarded_app():
    forwarded = parse_app_details(379880, {"379880": app_data(steam_appid=49520)})
    own = parse_app_details(49520, {"49520": app_data(steam_appid=49520)})
    absent = parse_app_details(1, {"1": {"success": False}})

    assert (forwarded.app_type, forwarded.forwarded_to) == ("game", 49520)
    assert (own.app_type, own.forwarded_to) == ("game", None)
    assert (absent.app_type, absent.forwarded_to) == (None, None)


def test_choose_app_id_follows_what_the_korean_store_sells():
    # Borderlands 2: 379880을 물으면 49520의 정보가 온다
    borderlands = [details(379880, price=21000, forwarded_to=49520), details(49520, price=21000)]
    assert choose_app_id(borderlands) == 49520
    # Mass Effect 2: 옛 앱은 가격이 없고 새 앱이 팔린다. 작은 id를 고르면 살 수 없는 게임이 된다
    assert choose_app_id([details(24980), details(2362420, price=33000)]) == 2362420
    # 무료 데모·유료 DLC가 아니라 본편
    stanley = [details(221910, price=16000), details(247750, free=True, app_type="demo")]
    assert choose_app_id(stanley) == 221910
    halo = [details(1240440, free=True), details(1708091, price=67000, app_type="dlc")]
    assert choose_app_id(halo) == 1240440
    # Black Ops 6: 작은 id는 가격 없는 다른 앱으로 넘어간다
    black_ops = [details(2933620, forwarded_to=1938090), details(4384550, price=97900)]
    assert choose_app_id(black_ops) == 4384550
    # Shogun 2: 본편 id에는 가격이 없고 넘어가는 id에만 있다 → 가격이 나오는 id
    shogun = [details(34330), details(201270, price=30000, forwarded_to=34330)]
    assert choose_app_id(shogun) == 201270


def test_choose_app_id_when_no_app_is_purchasable():
    # 둘 다 판매 중단(GTA: San Andreas) → 작은 id. 가격 판정이 '구매 불가'를 낸다
    assert choose_app_id([details(12250), details(12120)]) == 12120
    # 둘 다 한국 미판매(Final Fantasy XIV) → 작은 id. 가격 판정이 '한국 스토어 미판매'를 낸다
    assert choose_app_id([missing(262341), missing(39210)]) == 39210
    # 조회에 실패한 앱이 팔리는 앱일 수 있다 → 고르지 않고 폴백으로 보낸다
    assert choose_app_id([details(24980), None]) is None
    assert choose_app_id([None, details(2362420, price=33000)]) == 2362420
    # 본편이 없다
    assert choose_app_id([details(247890, free=True, app_type="demo")]) is None


def test_client_pick_reuses_the_response_for_price_lookup():
    client, calls = make_client(
        {49520: app_data(steam_appid=49520), 379880: app_data(steam_appid=49520)}
    )

    async def pick_then_price():
        app_id = await client.pick_app_id([49520, 379880])
        return app_id, await client.fetch_prices([game(1, app_id)])

    app_id, prices = asyncio.run(pick_then_price())

    assert app_id == 49520
    assert prices[0].amount_krw == 27000
    assert sorted(app_id for app_id, _, _ in calls) == [49520, 379880]  # 가격은 다시 묻지 않는다


def test_client_pick_does_not_guess_when_a_lookup_fails():
    def handler(request: httpx2.Request) -> httpx2.Response:
        app_id = int(request.url.params["appids"])
        if app_id == 2362420:
            return httpx2.Response(429)
        payload = {str(app_id): app_data(price_overview=None, packages=[])}
        return httpx2.Response(200, content=json.dumps(payload))

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    client = SteamStoreClient(http, FakeSpecJudge())

    assert asyncio.run(client.pick_app_id([24980, 2362420])) is None
