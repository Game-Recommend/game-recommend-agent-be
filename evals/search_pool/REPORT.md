# 검색 후보 풀 최초 실측

2026-09-19. 100문항(입력은 엔드투엔드 실행 `20260919T114056Z`에서 파서가 낸 조건). LLM 호출 없음.
평가 설계는 [README.md](README.md), 원시 기록은 [runs/before](runs/before)·[runs/after](runs/after)에 있다.

## 원인: 후보를 IGDB id 순으로 뽑고 있었다

엔드투엔드 평가에서 원본과 에이전트 모두 "Thief II: The Metal Age"를 추천을 낸 문항의 60% 이상에서
추천했다(원본 55/81, 에이전트 50/78). `evals/agent_e2e/REPORT.md`의 발견 1-1은 "후보가 1990~2000년대
게임에 쏠린다"고만 적고 원인을 범위 밖으로 남겼다. 원인은 검색 쿼리 한 줄이었다.

```
where <장르·플랫폼 조건>; sort id asc; limit 500;   → 앞에서부터 30개
```

IGDB id는 등록 순서다. 조건 없이 조회하면 이렇게 나온다.

```
id=1  2000  Thief II: The Metal Age        id=5  1998  Baldur's Gate
id=2  1998  Thief: The Dark Project        id=6  2000  Baldur's Gate II: Shadows of Amn
id=3  2004  Thief: Deadly Shadows          id=7  1995  Jagged Alliance
id=4  2014  Thief                          id=9  1999  Jagged Alliance 2
```

추천 목록에 나오던 순서 그대로다. 검색이 아니라 IGDB 테이블의 앞쪽 행을 읽고 있었다. 장르 조건을 붙여도
그 장르의 가장 낮은 id들이 올 뿐이다(RPG → Baldur's Gate, Jagged Alliance 2, Jade Empire, Fallout).

## 수정

- `sort total_rating_count desc`. 많이 평가된 게임이 앞에 온다.
- 본편·리메이크·리마스터·확장판만(`game_type = (0,8,9,10)`), 평가 5개 이상. 옛 필드 `category = 0`은
  이제 0건을 돌려준다.
- 플랫폼을 말하지 않으면 PC로 본다. 가격·사양 판정이 PC 기준이다. **Steam 연결은 요구하지 않는다.**
  LoL 같은 비Steam PC 게임은 기존 폴백(`evals/non_steam/`)이 다룬다.
- 분류어가 IGDB 장르 23개·테마 22개에 없으면 게임 모드(`Co-operative` 등)나 키워드로 찾는다. 조건을
  버리지 않는다.
- `play_mode`를 `game_modes` 조건으로 쓴다. 전에는 검색이 읽지 않았다.
- 인원 조건은 `connection`이 있으면 그쪽(online/local) 인원만 본다.
- `노트북`·`데스크톱`·`스팀`은 PC로 본다. 제외 분류는 이름에 들어 있기만 해도 거른다(`Turn-based` → TBS).

## 결과

| | 수정 전 | 수정 후 |
| --- | --- | --- |
| 후보 0개 문항 | 3 (E056, E081, E097) | 1 (E056) |
| 출시 연도 중앙값 | 2000 | 2011 |
| Steam 앱 id가 연결된 후보 | 61% | 76% |
| 상위 10개: 한국 스토어에서 조회됨 | 94% | 100% |
| 상위 10개: **최소 사양을 읽을 수 있음** | **53%** | **98%** |
| 상위 10개: 가격이 있음(무료 포함) | 93% | 89% |
| 상위 10개: 1만 원 이하 | 32% | **6%** |
| 상위 10개: 3만 원 이하 | 93% | **56%** |
| 상위 10개: 무료 | 0.4% | 0.5% |
| 상위 10개: 가격 중앙값 | 17,000원 | 21,000원 |
| 서로 다른 게임 수(전체 / 앞쪽 5개) | 260 / 51 | 274 / 48 |
| 앞쪽 5개에 가장 자주 드는 게임 | Thief: The Dark Project, 69문항 | Portal 2, 75문항 |

문항별로 보면 이렇게 바뀐다.

```
게임 1개만 추천해줘 {}
  전: Thief II: The Metal Age, Thief: The Dark Project, Thief: Deadly Shadows, Thief, Baldur's Gate
  후: Grand Theft Auto V, The Witcher 3: Wild Hunt, Portal 2, The Elder Scrolls V: Skyrim, GTA: San Andreas

협동 게임 3개만 추천해줘 {play_mode: cooperative}
  전: Thief II, Thief: The Dark Project, ... (play_mode를 검색이 읽지 않아 조건 없는 질문과 같았다)
  후: Grand Theft Auto V, Portal 2, Grand Theft Auto: San Andreas, Red Dead Redemption 2, Elden Ring

친구 한 명과 한 화면에서 할 2만 원 이하 협동 게임 {genres: [Cooperative], players: 2, connection: local}
  전: 후보 0개 (IGDB에 Cooperative라는 장르·테마가 없다)
  후: Portal 2, Grand Theft Auto: San Andreas, Far Cry 3, Borderlands 2, Baldur's Gate III

내 노트북이 i5-1240P ... {platforms: [노트북]}
  전: 후보 0개
  후: Grand Theft Auto V, The Witcher 3: Wild Hunt, Portal 2, ...
```

## 읽을 점

- **나아진 것.** 후보가 지금 팔리는 게임이 됐다. 사양 판정은 요구 사양을 읽을 수 있어야 의미가 있는데
  그 비율이 53% → 98%다. 조건 매핑이 어긋나 후보가 0개이던 두 문항이 살아났다.
- **그대로인 것.** 같은 게임이 질문과 무관하게 앞에 오는 정도는 변하지 않았다(69문항 → 75문항). 100문항
  중 60문항이 검색 조건이 없거나(22) 장르 하나뿐이거나(22) 플랫폼뿐이고(16), 예산·사양·개수는 검색 뒤의
  단계가 쓰기 때문이다.
  정렬을 바꾸는 것으로는 풀리지 않는다. 통과 후보 중에서 질문에 맞게 고르는 일은 에이전트가 맡는다
  (`evals/agent_e2e/REPORT.md`의 2026-09-19 검색 절).
- **나빠진 것.** 인기 게임은 비싸다. 상위 10개 중 1만 원 이하가 32% → 6%, 3만 원 이하가 93% → 56%다.
  고전 게임 풀이 우연히 낮은 예산에 맞았던 것이다. 낮은 예산·저사양 질문에서 빈 추천이 늘 수 있다.
- **무료 질문은 풀리지 않는다.** IGDB에는 가격이 없어 인기순 상위 30개에 무료 게임이 거의 없다(0.5%).
  무료 강제 질문은 후보를 다르게 뽑아야 한다. IGDB의 `popularity_primitives`에 Steam 동시 접속자
  (`24hr Peak Players`)가 있고 그 상위는 무료 게임 비중이 높다. 아직 재지 않은 가설이다.
- E056은 파서가 `genres=["Horror"]`와 `excluded_genres=["Horror"]`를 함께 냈다. 후보 0개가 옳다.

## 후보 수를 늘릴 수 없는 이유

Steam 상세 API는 앱 하나에 한 번 호출이고 IP당 5분에 약 200회 제한이다. 요청 하나가 후보 30개를
조회하므로 후보를 늘려 가격으로 거르는 방식은 쓰기 어렵다. 인기순에서는 같은 게임이 여러 요청에
반복되어 10분 캐시(`SteamStoreClient`)가 더 잘 맞는다.
