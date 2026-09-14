# 비Steam 폴백 평가 문항 40개

`steam_app_id`가 없는 후보가 타는 폴백(PCGamingWiki 사양, 무료 게임 표 → CheapShark + 환율)의 실측 평가셋 v3.
실행 입력은 dataset.json이며, 이 문서는 사람이 읽는 설명이다. 질문 파서·IGDB 검색·리뷰·최종 답변은 평가하지 않는다.

이력: v1 라벨은 실행 전에 사전 지식으로 적었다. v2에서 CheapShark 실측으로 P08·P10·P12를 정정했다.
v3에서 사양 출처를 RAWG에서 PCGamingWiki로 바꾸며 W축(구 R축)의 기대값을 다시 적었다(W05 Fortnite: 미매칭 → 매칭).
정정 내역은 각 행의 비고에 남겼다.

## W: PCGamingWiki 사양 커버리지 (20)

기대값이 있는 행만 통과/실패를 매기고, 나머지는 매칭·사양 유무·파싱 항목 수를 기록만 한다.

| ID | 게임 | 기대 매칭 | 비고 |
|---|---|---|---|
| W01 | League of Legends | 매칭 | 자체 런처 무료 |
| W02 | VALORANT | 매칭 | 자체 런처 무료 |
| W03 | Teamfight Tactics | 기록 | LoL 클라이언트 내 모드 |
| W04 | Legends of Runeterra | 기록 | |
| W05 | Fortnite | 매칭 | v3 정정: PCGamingWiki에는 'Fortnite'로 등록 |
| W06 | Genshin Impact | 매칭 | minGPU2에 Intel Iris Xe: 대안 GPU 결합 확인 |
| W07 | Honkai: Star Rail | 기록 | 콜론 포함 제목 |
| W08 | Zenless Zone Zero | 기록 | |
| W09 | Wuthering Waves | 기록 | |
| W10 | Roblox | 기록 | 템플릿에 GPU 없음 |
| W11 | Hearthstone | 기록 | |
| W12 | World of Warcraft | 기록 | 구독제, Battle.net |
| W13 | Diablo Immortal | 기록 | |
| W14 | Minecraft | 기록 | 자체 런처 유료 |
| W15 | Escape from Tarkov | 기록 | 자체 런처 유료 |
| W16 | Alan Wake 2 | 매칭 | Epic 독점 유료. 'Alan Wake II'로 리다이렉트 |
| W17 | Kingdom Hearts III | 기록 | Epic 선출시 |
| W18 | Rocket League | 기록 | Epic 무료 전환 |
| W19 | Final Fantasy VII Remake Intergrade | 기록 | 긴 제목 |
| W20 | Some Nonexistent Game 9999 | 미매칭 | 음성 대조군 |

## P: 가격 폴백 (15)

`free`는 무료 표 적중(0원), `quoted`는 CheapShark 정확 일치 후 원화 변환(범위 검사), `omitted`는 결과 생략(→ unknown)이다.
`unavailable`(PriceUnavailable)은 어떤 경우에도 나오면 안 된다. 폴백은 미판매를 확인할 수 없기 때문이다.

| ID | 입력 제목 | 기대 | 원화 범위 | 비고 |
|---|---|---|---|---|
| P01 | League of Legends | free | | |
| P02 | VALORANT | free | | |
| P03 | Genshin Impact | free | | |
| P04 | Fortnite | free | | |
| P05 | Roblox | free | | |
| P06 | honkai star rail | free | | 정규화 비교: 콜론·대소문자 차이 |
| P07 | Alan Wake 2 | quoted | 20,000~150,000 | CheapShark 정확 일치 |
| P08 | Kingdom Hearts III | omitted | | v2 정정: CheapShark에 이 제목의 단독 항목 없음 |
| P09 | Alan Wake | quoted | 1,000~60,000 | 'Alan Wake 2'와 섞이면 안 됨 |
| P10 | Alan Wake 2 Deluxe Edition | quoted | 10,000~150,000 | v2 정정: 같은 이름의 에디션 항목이 있어 정확 일치. 본편과 섞이면 안 됨 |
| P11 | Alan Wake 2: Night Springs | omitted | | DLC 이름은 정확 일치 실패 |
| P12 | Escape from Tarkov | quoted | 20,000~100,000 | v2 정정: CheapShark 취급 |
| P13 | World of Warcraft | omitted | | 구독제, 무료 표에도 없음 |
| P14 | Some Nonexistent Game 9999 | omitted | | 음성 대조군 |
| P15 | Minecraft | omitted | | 자체 런처, CheapShark 미취급 |

## C: 판정 일관성 (5)

같은 최소 사양(Windows 10 64-bit, i5-4460, 8 GB, GT 1030)을 Steam HTML과 PCGamingWiki `System requirements`
템플릿(위키 링크·`<ref>`·`{{ii}}` 포함)으로 넣고, 파싱된 네 항목이 같은지와 판정 상태가 같은지를 본다.
C03·C04만 실제 LLM 판정기를 쓴다.

| ID | 사용자 사양 | 기대 | LLM |
|---|---|---|---|
| C01 | RAM 4 GB | unmet | 아니오 |
| C02 | RAM 16 GB | met | 아니오 |
| C03 | GT 1030, RAM 16 GB | met | 예 |
| C04 | i5-4460, RAM 8 GB | met | 예 |
| C05 | "GeForce", RAM 16 GB | skipped | 아니오 |
