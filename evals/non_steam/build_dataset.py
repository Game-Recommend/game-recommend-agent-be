"""Steam에 없는 후보의 폴백 평가셋. 실제 API 결과로 정답을 만들지 않는다.

세 축으로 나뉜다.
- W: PCGamingWiki 사양 커버리지. 매칭 여부·사양 유무·파싱 항목 수를 기록한다. 기대값은 사전 지식이
  확실한 경우만 적고 나머지는 null로 두어 기록만 한다.
- P: 가격 폴백. 무료 표 적중(0원), CheapShark 정확 일치(원화 범위), 정확 일치 실패(생략)를 본다.
- C: 판정 일관성. 같은 사양을 Steam HTML과 PCGamingWiki 템플릿으로 넣었을 때 판정이 같아야 한다.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
cases: list[dict] = []


def wiki(name, *, expected_match=None, note=""):
    cases.append(
        {
            "id": f"W{len([c for c in cases if c['kind'] == 'wiki']) + 1:02}",
            "kind": "wiki",
            "name": name,
            "expected_match": expected_match,  # True/False/None(기록만)
            "note": note,
        }
    )


def price(name, expected, *, krw_range=None, note=""):
    cases.append(
        {
            "id": f"P{len([c for c in cases if c['kind'] == 'price']) + 1:02}",
            "kind": "price",
            "name": name,
            "expected": expected,  # "free" | "quoted" | "omitted"
            "krw_range": krw_range,  # quoted일 때 [최소, 최대]
            "note": note,
        }
    )


def consistency(category, user, steam_html, wikitext, expected, *, llm=True):
    cases.append(
        {
            "id": f"C{len([c for c in cases if c['kind'] == 'consistency']) + 1:02}",
            "kind": "consistency",
            "category": category,
            "hardware": user,
            "steam_html": steam_html,
            "wikitext": wikitext,
            "expected": expected,
            "expects_llm": llm,
        }
    )


# ---------- W: PCGamingWiki 커버리지 20 ----------
wiki("League of Legends", expected_match=True, note="자체 런처 무료")
wiki("VALORANT", expected_match=True, note="자체 런처 무료")
wiki("Teamfight Tactics", note="LoL 클라이언트 내 모드")
wiki("Legends of Runeterra")
wiki("Fortnite", expected_match=True, note="v3 정정: PCGamingWiki에는 'Fortnite'로 등록")
wiki("Genshin Impact", expected_match=True, note="minGPU2에 Intel Iris Xe: 대안 GPU 결합 확인")
wiki("Honkai: Star Rail", note="콜론 포함 제목")
wiki("Zenless Zone Zero")
wiki("Wuthering Waves")
wiki("Roblox", note="템플릿에 GPU 없음")
wiki("Hearthstone")
wiki("World of Warcraft", note="구독제, Battle.net")
wiki("Diablo Immortal")
wiki("Minecraft", note="자체 런처 유료")
wiki("Escape from Tarkov", note="자체 런처 유료")
wiki("Alan Wake 2", expected_match=True, note="Epic 독점 유료. 'Alan Wake II'로 리다이렉트")
wiki("Kingdom Hearts III", note="Epic 선출시")
wiki("Rocket League", note="Epic 무료 전환")
wiki("Final Fantasy VII Remake Intergrade", note="긴 제목")
wiki("Some Nonexistent Game 9999", expected_match=False, note="음성 대조군")

# ---------- P: 가격 폴백 15 ----------
price("League of Legends", "free")
price("VALORANT", "free")
price("Genshin Impact", "free")
price("Fortnite", "free")
price("Roblox", "free")
price("honkai star rail", "free", note="정규화 비교: 콜론·대소문자 차이")
price("Alan Wake 2", "quoted", krw_range=[20000, 150000], note="CheapShark 정확 일치")
price(
    "Kingdom Hearts III", "omitted", note="v2 정정: CheapShark에 이 제목의 단독 항목 없음"
)
price("Alan Wake", "quoted", krw_range=[1000, 60000], note="'Alan Wake 2'와 섞이면 안 됨")
price(
    "Alan Wake 2 Deluxe Edition",
    "quoted",
    krw_range=[10000, 150000],
    note="v2 정정: CheapShark에 같은 이름의 에디션 항목이 있어 정확 일치. 본편과 섞이면 안 됨",
)
price("Alan Wake 2: Night Springs", "omitted", note="DLC 이름은 정확 일치 실패")
price(
    "Escape from Tarkov", "quoted", krw_range=[20000, 100000], note="v2 정정: CheapShark 취급"
)
price("World of Warcraft", "omitted", note="구독제, 무료 표에도 없음")
price("Some Nonexistent Game 9999", "omitted", note="음성 대조군")
price("Minecraft", "omitted", note="자체 런처, CheapShark 미취급")

# ---------- C: 판정 일관성 5 ----------
STEAM_HTML = (
    '<strong>Minimum:</strong><br><ul class="bb_ul">'
    "<li><strong>OS:</strong> Windows 10 64-bit<br></li>"
    "<li><strong>Processor:</strong> Intel Core i5-4460<br></li>"
    "<li><strong>Memory:</strong> 8 GB RAM<br></li>"
    "<li><strong>Graphics:</strong> NVIDIA GeForce GT 1030<br></li>"
    "<li><strong>DirectX:</strong> Version 11<br></li></ul>"
)
WIKITEXT = (
    "{{System requirements\n|OSfamily = Windows\n|ref=<ref name=\"SysReqs\"/>\n\n"
    "|minOS    = 10 64-bit\n|minCPU   = Intel Core i5-4460\n|minRAM   = 8 GB\n"
    "|minGPU   = [[NVIDIA GeForce GT 1030]]\n|minDX    = 11\n"
    "|notes    = {{ii}} [https://example.com/official Official system requirements]\n}}"
)
consistency("RAM 부족", {"ram_gb": 4}, STEAM_HTML, WIKITEXT, "unmet", llm=False)
consistency("RAM 충족만", {"ram_gb": 16}, STEAM_HTML, WIKITEXT, "met", llm=False)
consistency(
    "GPU 동일", {"gpu": "NVIDIA GeForce GT 1030", "ram_gb": 16}, STEAM_HTML, WIKITEXT, "met"
)
consistency("CPU 동일", {"cpu": "Intel Core i5-4460", "ram_gb": 8}, STEAM_HTML, WIKITEXT, "met")
consistency(
    "모델 불명 GPU", {"gpu": "GeForce", "ram_gb": 16}, STEAM_HTML, WIKITEXT, "skipped", llm=False
)

ROOT.joinpath("dataset.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
print(f"{len(cases)} cases written")
