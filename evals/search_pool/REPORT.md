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

## 분류 조건을 id로 걸고, 지어낸 분류는 키워드로 찾는다 (2026-09-20)

취향 적합도 평가(`evals/relevance`)의 빈 추천 8건이 모두 검색 후보 0개였다. 원인은 둘이다.

### 1. 같은 배열에 이름 조건을 둘 걸면 0건이다

검색은 분류마다 `(genres.name ~ "x" | themes.name ~ "x")`를 만들어 `&`로 이었다. IGDB는 같은 배열의
하위 필드 조건 둘을 **한 원소가 동시에 만족**해야 한다고 읽는다.

```
"판타지 배경의 액션 RPG" → genres=["Fantasy", "Action", "Role-playing (RPG)"]
  Fantasy + RPG     (테마 + 장르)  → 후보 있음
  Fantasy + Action  (테마 + 테마)  → 0건   ← 한 테마가 Fantasy이면서 Action일 수는 없다
  themes = [17,1]   (id, 모두 포함) → The Witcher 3, Skyrim, God of War, ...
```

게임 모드도 같은 배열이라 `genres=["Multiplayer"]` + `play_mode="cooperative"`가 0건이었다. 정렬을
바꾸기 전부터 있던 문제다. 분류·게임 모드를 이름이 아니라 **id로** 걸고(`genres = [12]`,
`themes = [17,1]`, `game_modes = [2,3]`), 장르·테마·게임 모드의 id 표를 코드에 둔다.

### 2. 질문 분해가 지어낸 분류는 정확히 일치하는 키워드가 없다

"스토리 게임" → `genres=["Story"]`, "경쟁 게임" → `genres=["Competition"]`. IGDB에 그런 장르·테마는
없고, `keywords.name ~ "story"`(정확 일치)도 0건이다. 부분 일치(`~ *"story"*`)는 28개를 돌려주지만
"alternate history"가 딸려 온다.

키워드 이름을 먼저 조회해 **어떤 단어가 그 말로 시작하는 것만** id로 남긴다. "story rich"·"emotional
story"·"branching storyline"은 남고 "history"는 빠진다. 긴 말은 끝을 잘라 찾는다(`competition` →
`competit`로 `competitive`도 찾는다). 분류어가 여럿이면 키워드는 하나만 맞아도 된다(뜻이 넓은 말을 푼
것이라서). 맞는 키워드가 하나도 없으면 전처럼 후보가 없다. 조건을 버리고 아무 게임이나 돌려주지 않는다.
IGDB 호출은 그런 분류어가 있을 때만 한 번 늘어난다.

### 결과

입력을 엔드투엔드 100문항 + 취향 적합도 평가 40문항의 조건(140문항)으로 넓혀 전후를 쟀다
([runs/before-category-fix](runs/before-category-fix), [runs/after-category-fix](runs/after-category-fix),
Steam 조회 생략).

| | 수정 전 | 수정 후 |
| --- | --- | --- |
| 후보 0개 문항 | 5 (E056, R033, R037, R038, R040) | 1 (E056) |
| 후보 목록이 달라진 문항 | | 4 (위의 R 문항 넷) |
| 나머지 136문항의 후보 목록 | | **수정 전과 같다** |

```
SF 세계관의 스토리 게임 {genres: [Science fiction, Story]}
  후: Mass Effect 2, BioShock Infinite, Fallout: New Vegas, Life Is Strange, Fallout 3, Cyberpunk 2077
엔딩까지 10시간 이하인 스토리 게임 {genres: [Story], max_playtime_hours: 10}
  후: Undertale, Call of Duty: Black Ops II, Bastion, Little Nightmares, Stray, Papers, Please
판타지 배경의 액션 RPG {genres: [Fantasy, Action, Role-playing (RPG)]}
  후: The Witcher 3, Skyrim, God of War, Elden Ring, Dark Souls III, Hades
한 판이 짧은 경쟁 게임 {genres: [Competition], play_mode: competitive}
  후: Counter-Strike: Global Offensive, Overwatch, StarCraft II: Wings of Liberty, Call of Duty: World at War, Counter-Strike, Halo 3: ODST
```

- 분류가 하나인 질문은 id로 바꿔도 결과가 같다. 136문항이 그대로인 것이 그 확인이다.
- E056은 기록된 조건이 `genres=["Horror"]` + `excluded_genres=["Horror"]`로 모순이라 0개가 옳다. 지금의
  질문 분해는 이 모순을 내지 않는다(같은 분류가 양쪽에 있으면 제외가 이긴다).
- 빈손이던 취향 적합도 문항 다섯 개를 에이전트로 다시 돌리면 넷이 추천을 냈다(R037은 Undertale, Little
  Nightmares, Papers, Please, Stray). R033은 에이전트 루프 실패로 끝났는데, 같은 질문을 두 번 더 돌리면
  추천을 낸다. 검색과 무관한 도구 반복 호출 문제다(`evals/agent_e2e/REPORT.md`의 E095).
