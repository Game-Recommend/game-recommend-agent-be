# 예상 질문 5개 전후 비교 실측

2026-09-17 측정. 루트 [README](../../README.md)의 `## 예상 질문` 5개를 원본
[game-recommend-be](https://github.com/Game-Recommend/game-recommend-be)(고정 파이프라인)와 이 저장소
(에이전트)로 각각 한 번씩 실행했다. 두 저장소 모두 `gpt-4o-mini` 기본값이고, 원시 기록은
[runs/2026-09-17](runs/2026-09-17)에 있다.

**2026-09-20에 에이전트만 다시 쟀다.** 그 수치와 달라진 점은 맨 아래
[재측정](#재측정-2026-09-20-에이전트만) 절에 있고, 아래 본문은 2026-09-17의 측정 그대로다.

실제 외부 API와 LLM을 부른 한 번의 측정이다. 지연과 후보 구성은 IGDB·Steam 응답과 모델 상태에 따라
흔들리므로 추세로 읽고, 숫자를 재현하려면 같은 날짜의 원시 기록을 본다.

## 요약

| 질문 유형 | 원본 (고정 파이프라인) | 에이전트 | 에이전트가 부른 Tool (순서) |
| --- | --- | --- | --- |
| 하드웨어 | 4.87초 · 0개 | 30.05초 · 3개 | 게임 검색 → 하드웨어 → 리뷰 점수 → 리뷰 요약 → 가격 |
| 멀티플레이 + 인원 | 17.48초 · 5개 | 27.07초 · 5개 | 게임 검색 → 가격 → 하드웨어 → 리뷰 점수 → 리뷰 요약 → 리뷰 요약 |
| 가격 + 취향 | 22.47초 · 5개 | 28.76초 · 5개 | 게임 검색 → 가격 → 하드웨어 → 리뷰 점수 → 리뷰 요약 |
| 플레이타임 + 장르 | 16.14초 · 5개 | 40.07초 · 5개 | 게임 검색 → 가격 → 하드웨어 → 리뷰 점수 → 리뷰 요약 |
| 복합 조건 (데모용) | 24.77초 · 3개 | 19.71초 · 2개 | 게임 검색 → 가격 → 하드웨어 → 리뷰 점수 → 리뷰 요약 → 리뷰 요약 |

## 이번 측정에서 본 차이

- **검색이 비면 고정 파이프라인은 거기서 끝난다.** 하드웨어 질문에서 원본은 충족 후보를 찾지 못해
  4.9초 만에 "추천할 게임이 없다"로 끝냈다(단계도 질문 분해 → 게임 검색 → 최종 답변뿐이다).
  에이전트는 같은 질문에서 검색 인자를 LLM이 직접 정해 후보 30개를 얻고 Tool 5개를 부른 뒤 3개를 추천했다.
- **도구 순서와 횟수가 질문마다 달라진다.** 원본은 늘 검색 → 가격 → 하드웨어 → 리뷰 요약 → 미디어
  한 바퀴다. 에이전트는 사양을 먼저 보기도 하고(하드웨어 질문), 리뷰 요약을 두 번 부르기도 한다.
- **대신 느리다.** 원본 4.9~24.8초, 에이전트 19.7~40.1초다. LLM이 도구를 고르는 왕복이 더해진 값이다.
- **제외 목록은 에이전트가 얇다.** 복합 조건 질문에서 원본은 후보 전체를 조회해 20개를 제외 목록에
  남겼지만, 에이전트는 LLM이 고른 일부만 조회해 1개만 남겼다. 조회하지 않은 후보는 판단한 적이 없으므로
  제외 목록에 넣지 않는다는 `CandidateStore.checked()` 규칙 때문이다. FE의 "제외된 게임" 카드가
  원본보다 빈약해지는 대가다.

## 타임라인 읽는 법

- 같은 시각에 시작한 Tool 단계는 에이전트가 한 턴에 함께 부른 것이다(같은 턴 병렬 호출).
  멀티플레이 질문의 `가격`·`하드웨어`가 5.74초에 같이 시작한다.
- `에이전트 추론`이 완료된 뒤에 나오는 Tool 단계는 러너 안전망이 직접 부른 것이다. 멀티플레이 질문의
  26.38초 `리뷰 요약`이 그것이고, Steam 리뷰가 없는 League of Legends가 경고로 남았다.
- 예산·사양 조건이 없어도 답변과 카드에 쓰려고 가격·사양을 조회한다. 조건이 없으면 판정은 `skipped`다.
- 하드웨어 질문의 `가격`은 27.24초에 시작해 같은 초에 끝난다. 앞선 `하드웨어` 조회가 같은
  `SteamStoreClient`로 appdetails를 이미 받아둔 덕이다.

## 질문별 상세

### 하드웨어

> 내 노트북이 i5-1240P, RAM 16GB, 내장그래픽인데 원활하게 할 수 있는 게임 중에서 평점 좋은 게임 추천해줘.

- **원본** (4.87초, 추천 0개): 추천 없음
  - 제외 0개 · 경고 1건
    - 모든 필수 조건을 충족한다고 확인된 후보가 없습니다.
- **에이전트** (30.05초, 추천 3개): Thief II: The Metal Age, BioShock, BioShock 2
  - 제외 9개 · 경고 0건

에이전트 타임라인:

```text
  0.00s  질문 분해     started
  2.04s  질문 분해     completed
  2.04s  에이전트 추론   started
  2.83s  게임 검색     started
  5.56s  게임 검색     completed · 후보 30개
  6.79s  하드웨어      started
  8.08s  하드웨어      completed
  9.05s  리뷰 점수     started
  9.47s  리뷰 점수     completed
 10.86s  리뷰 요약     started
 24.94s  리뷰 요약     completed
 27.24s  가격        started
 27.24s  가격        completed
 29.14s  에이전트 추론   completed · 도구 호출 4회
 29.14s  조건 판정     completed · 추천 3개, 제외 9개
 29.14s  미디어       started
 30.05s  미디어       completed
```

### 멀티플레이 + 인원

> 친구 4명이서 온라인으로 같이 할 게임을 찾고 있어. 경쟁보다는 협동 위주였으면 좋겠고 한 판이 너무 길지 않았으면 좋겠어.

- **원본** (17.48초, 추천 5개): Baldur's Gate II: Shadows of Amn, BioShock 2, Dead Space 2, League of Legends, Left 4 Dead 2
  - 제외 6개 · 경고 3건
    - Baldur's Gate II: Shadows of Amn: 리뷰 요약 확인 불가
    - Baldur's Gate II: Shadows of Amn: 원화 가격 확인 불가
    - League of Legends: 리뷰 요약 확인 불가
- **에이전트** (27.07초, 추천 5개): BioShock 2, Dead Space 2, League of Legends, Left 4 Dead 2, Star Wars: Jedi Knight - Dark Forces II
  - 제외 6개 · 경고 1건
    - League of Legends: 리뷰 요약 확인 불가

에이전트 타임라인:

```text
  0.00s  질문 분해     started
  1.28s  질문 분해     completed
  1.28s  에이전트 추론   started
  2.23s  게임 검색     started
  3.82s  게임 검색     completed · 후보 30개
  5.74s  가격        started
  5.74s  하드웨어      started
  7.46s  가격        completed
 12.05s  하드웨어      completed
 13.09s  리뷰 점수     started
 13.65s  리뷰 점수     completed
 14.91s  리뷰 요약     started
 23.60s  리뷰 요약     completed
 26.38s  에이전트 추론   completed · 도구 호출 5회
 26.38s  조건 판정     completed · 추천 5개, 제외 6개
 26.38s  리뷰 요약     started
 26.38s  리뷰 요약     completed
 26.38s  미디어       started
 27.07s  미디어       completed
```

### 가격 + 취향

> 지금 2만 원 이하로 살 수 있는 게임 중에서 스토리가 중요한 RPG 추천해줘. 턴제 게임은 별로 안 좋아해.

- **원본** (22.47초, 추천 5개): Jade Empire: Special Edition, Vampire: The Masquerade - Bloodlines, Vampire: The Masquerade - Redemption, Fallout: A Post Nuclear Role Playing Game, Fallout 2
  - 제외 10개 · 경고 0건
- **에이전트** (28.76초, 추천 5개): Jade Empire: Special Edition, Vampire: The Masquerade - Bloodlines, Vampire: The Masquerade - Redemption, Fallout 2, Fallout 3
  - 제외 1개 · 경고 0건

에이전트 타임라인:

```text
  0.00s  질문 분해     started
  1.35s  질문 분해     completed
  1.35s  에이전트 추론   started
  3.65s  게임 검색     started
  7.02s  게임 검색     completed · 후보 30개
  8.79s  가격        started
  8.79s  하드웨어      started
  9.05s  하드웨어      completed
 10.50s  가격        completed
 11.60s  리뷰 점수     started
 12.04s  리뷰 점수     completed
 12.82s  리뷰 요약     started
 25.49s  리뷰 요약     completed
 28.18s  에이전트 추론   completed · 도구 호출 5회
 28.18s  조건 판정     completed · 추천 5개, 제외 1개
 28.18s  미디어       started
 28.76s  미디어       completed
```

### 플레이타임 + 장르

> 취업 준비하면서 가볍게 할 게임을 찾고 있어. 한 번에 30분~1시간 정도 하기 좋고, 전체 플레이타임도 15시간을 넘지 않는 싱글 게임이면 좋겠어.

- **원본** (16.14초, 추천 5개): Max Payne 2: The Fall of Max Payne, BioShock 2, System Shock 2, Overlord: Raising Hell, Syndicate
  - 제외 3개 · 경고 3건
    - System Shock 2: 리뷰 요약 확인 불가
    - Syndicate: 리뷰 요약 확인 불가
    - Syndicate: 원화 가격 확인 불가
- **에이전트** (40.07초, 추천 5개): Max Payne 2: The Fall of Max Payne, BioShock 2, Overlord: Raising Hell, The Curse of Monkey Island, Portal 2
  - 제외 3개 · 경고 0건

에이전트 타임라인:

```text
  0.00s  질문 분해     started
  1.35s  질문 분해     completed
  1.35s  에이전트 추론   started
  2.33s  게임 검색     started
  4.75s  게임 검색     completed · 후보 30개
  7.00s  가격        started
  7.00s  하드웨어      started
 10.21s  가격        completed
 13.08s  하드웨어      completed
 14.22s  리뷰 점수     started
 14.99s  리뷰 점수     completed
 15.94s  리뷰 요약     started
 36.72s  리뷰 요약     completed
 39.63s  에이전트 추론   completed · 도구 호출 5회
 39.63s  조건 판정     completed · 추천 5개, 제외 3개
 39.63s  미디어       started
 40.07s  미디어       completed
```

### 복합 조건 (데모용)

> RTX 3060, RAM 16GB PC를 사용하고 있어. 친구 한 명과 온라인으로 같이 할 수 있고, 공포 게임은 싫어. 3만 원 이하이면서 Steam 평가가 좋은 게임 3개만 추천해줘.

- **원본** (24.77초, 추천 3개): Overlord II, Portal 2, Mass Effect 3
  - 제외 20개 · 경고 0건
- **에이전트** (19.71초, 추천 2개): Overlord II, Mass Effect 3
  - 제외 1개 · 경고 0건

에이전트 타임라인:

```text
  0.00s  질문 분해     started
  1.42s  질문 분해     completed
  1.42s  에이전트 추론   started
  2.60s  게임 검색     started
  6.74s  게임 검색     completed · 후보 30개
  7.84s  가격        started
  7.84s  하드웨어      started
  8.17s  가격        completed
  9.67s  하드웨어      completed
 10.73s  리뷰 점수     started
 10.95s  리뷰 점수     completed
 13.33s  리뷰 요약     started
 13.33s  리뷰 요약     started
 15.07s  리뷰 요약     completed
 17.25s  리뷰 요약     completed
 19.01s  에이전트 추론   completed · 도구 호출 6회
 19.01s  조건 판정     completed · 추천 2개, 제외 1개
 19.01s  미디어       started
 19.71s  미디어       completed
```

## 재측정 (2026-09-20, 에이전트만)

2026-09-17 뒤로 이 저장소에서 검색 후보 풀과 가격·사양의 후보 전체 조회(#29), 빈 초안·이름 되묻기
(#28·#29), 질문 분해의 제외 표현(#30), 분류 id 검색(#32), Tool별 호출 상한(#33)이 바뀌었다. 그래서
에이전트만 다시 쟀다. 원본 저장소의 앱 코드는 그 사이에 바뀌지 않아 2026-09-17의 기록을 그대로 쓴다.
원시 기록은 [runs/2026-09-20](runs/2026-09-20)에 있고, 루트 README의 표는 이 절의 표다.

"에이전트가 부른 Tool"은 이번부터 LLM이 부른 단계만 센다. `에이전트 추론`이 끝난 뒤 러너가 직접 부른
리뷰 요약은 뺀다([report.py](report.py)). 위 2026-09-17 표는 그 구분 없이 만든 것이다.

| 질문 유형 | 원본 (고정 파이프라인) | 에이전트 | 에이전트가 부른 Tool (순서) |
| --- | --- | --- | --- |
| 하드웨어 | 4.87초 · 0개 | 19.5초 · 5개 | 게임 검색 → 가격 → 하드웨어 → 리뷰 점수 → 리뷰 요약 → 리뷰 점수 → 리뷰 요약 |
| 멀티플레이 + 인원 | 17.48초 · 5개 | 10.97초 · 5개 | 게임 검색 → 가격 → 하드웨어 |
| 가격 + 취향 | 22.47초 · 5개 | 11.75초 · 5개 | 게임 검색 → 하드웨어 → 가격 |
| 플레이타임 + 장르 | 16.14초 · 5개 | 11.45초 · 4개 | 게임 검색 → 하드웨어 → 가격 → 리뷰 요약 |
| 복합 조건 (데모용) | 24.77초 · 3개 | 14.52초 · 3개 | 게임 검색 → 가격 → 하드웨어 → 리뷰 점수 → 리뷰 요약 |

### 달라진 점

- **에이전트가 빨라졌다.** 19.7~40.1초에서 11.0~19.5초가 됐다. 같은 Tool을 되풀이해 부르지 않고,
  리뷰 요약이 게임별 병렬 호출이라 1.8~2.4초에 끝난다(원본은 같은 단계에 5.8~13.7초를 쓴다). 추천을 낸
  네 질문에서는 원본보다 빠르다. 구조의 효과가 아니라 리뷰 요약 병렬화의 효과가 크다.
- **제외 목록이 채워진다.** 가격·사양이 검색된 후보 전체를 조회해서다. 복합 조건 질문에서 1개이던 제외
  근거가 19개가 됐다(원본 20개).
- **하드웨어 질문의 추천이 3개에서 5개가 됐다.** 검색이 `노트북`을 PC로 읽고 후보를 인기순으로 뽑는다.
  원본이 이 질문에서 빈손인 이유도 구조가 아니라 `노트북` 플랫폼으로 검색이 0건이어서다.
- **리뷰 Tool을 두 번씩 부른 질문이 있다.** 하드웨어 질문에서 `리뷰 점수`·`리뷰 요약`의 첫 호출은 후보에
  없는 id를 넘겨 바로 거부됐고(0.0초, 경고 없음), 고쳐 부른 두 번째 호출이 성공했다. Tool별 호출 상한이
  리뷰 Tool에 2회를 주는 이유가 이 경우다.

### 이번 기록에서 본 문제

- **질문에 없는 취향이 뽑혔다.** 멀티플레이 질문의 질문 분해 결과가 `preferences=["턴제 비선호"]`다.
  질문에는 턴제 이야기가 없고, 2026-09-17에는 `협동 선호`·`한 판이 너무 길지 않길 선호`가 뽑혔다. 같은
  질문으로 질문 분해만 6번 다시 부르면 1번 같은 결과가 나온다. 질문 분해 프롬프트의 예시 문구가 새어
  나온 것으로 보인다. 이 측정에서는 고치지 않았다.
- 플레이타임 질문은 5개를 받을 수 있는데 4개를 추천했다(통과 후보 28개). 개수는 상한이라 위반은 아니다.

### 질문별 상세 (2026-09-20)

#### 하드웨어

> 내 노트북이 i5-1240P, RAM 16GB, 내장그래픽인데 원활하게 할 수 있는 게임 중에서 평점 좋은 게임 추천해줘.

- **원본** (4.87초, 추천 0개): 추천 없음
  - 제외 0개 · 경고 1건
    - 모든 필수 조건을 충족한다고 확인된 후보가 없습니다.
- **에이전트** (19.5초, 추천 5개): The Witcher 3: Wild Hunt, Portal 2, The Elder Scrolls V: Skyrim, Assassin's Creed II, Half-Life 2
  - 제외 3개 · 경고 0건

에이전트 타임라인:

```text
  0.00s  질문 분해     started
  1.96s  질문 분해     completed
  1.96s  에이전트 추론   started
  3.09s  게임 검색     started
  5.55s  게임 검색     completed · 후보 30개
  6.87s  가격        started
  6.87s  하드웨어      started
  7.95s  가격        completed
  7.95s  하드웨어      completed
  9.23s  리뷰 점수     started
  9.23s  리뷰 점수     failed
  9.23s  리뷰 요약     started
  9.23s  리뷰 요약     failed
 12.06s  리뷰 점수     started
 12.06s  리뷰 요약     started
 12.32s  리뷰 점수     completed
 14.51s  리뷰 요약     completed
 18.70s  에이전트 추론   completed · 도구 호출 7회
 18.70s  조건 판정     completed · 통과 27개 중 5개 추천, 제외 3개
 18.70s  미디어       started
 19.50s  미디어       completed
```

#### 멀티플레이 + 인원

> 친구 4명이서 온라인으로 같이 할 게임을 찾고 있어. 경쟁보다는 협동 위주였으면 좋겠고 한 판이 너무 길지 않았으면 좋겠어.

- **원본** (17.48초, 추천 5개): Baldur's Gate II: Shadows of Amn, BioShock 2, Dead Space 2, League of Legends, Left 4 Dead 2
  - 제외 6개 · 경고 3건
    - Baldur's Gate II: Shadows of Amn: 리뷰 요약 확인 불가
    - Baldur's Gate II: Shadows of Amn: 원화 가격 확인 불가
    - League of Legends: 리뷰 요약 확인 불가
- **에이전트** (10.97초, 추천 5개): Dark Souls III, Call of Duty 4: Modern Warfare, Assassin's Creed IV Black Flag, Left 4 Dead 2, Watch Dogs
  - 제외 2개 · 경고 0건

에이전트 타임라인:

```text
  0.00s  질문 분해     started
  1.08s  질문 분해     completed
  1.08s  에이전트 추론   started
  1.80s  게임 검색     started
  3.48s  게임 검색     completed · 후보 30개
  4.37s  가격        started
  4.37s  하드웨어      started
  5.30s  가격        completed
  5.30s  하드웨어      completed
  9.10s  에이전트 추론   completed · 도구 호출 3회
  9.10s  조건 판정     completed · 통과 28개 중 5개 추천, 제외 2개
  9.10s  미디어       started
  9.10s  리뷰 요약     started
  9.73s  미디어       completed
 10.96s  리뷰 요약     completed
```

#### 가격 + 취향

> 지금 2만 원 이하로 살 수 있는 게임 중에서 스토리가 중요한 RPG 추천해줘. 턴제 게임은 별로 안 좋아해.

- **원본** (22.47초, 추천 5개): Jade Empire: Special Edition, Vampire: The Masquerade - Bloodlines, Vampire: The Masquerade - Redemption, Fallout: A Post Nuclear Role Playing Game, Fallout 2
  - 제외 10개 · 경고 0건
- **에이전트** (11.75초, 추천 5개): Mass Effect, Dishonored, Undertale, The Elder Scrolls IV: Oblivion, Star Wars: Knights of the Old Republic
  - 제외 21개 · 경고 0건

에이전트 타임라인:

```text
  0.00s  질문 분해     started
  1.18s  질문 분해     completed
  1.18s  에이전트 추론   started
  2.31s  게임 검색     started
  3.86s  게임 검색     completed · 후보 30개
  4.83s  하드웨어      started
  4.83s  가격        started
  5.74s  하드웨어      completed
  5.74s  가격        completed
  9.40s  에이전트 추론   completed · 도구 호출 3회
  9.40s  조건 판정     completed · 통과 9개 중 5개 추천, 제외 21개
  9.40s  미디어       started
  9.40s  리뷰 요약     started
  9.93s  미디어       completed
 11.75s  리뷰 요약     completed
```

#### 플레이타임 + 장르

> 취업 준비하면서 가볍게 할 게임을 찾고 있어. 한 번에 30분~1시간 정도 하기 좋고, 전체 플레이타임도 15시간을 넘지 않는 싱글 게임이면 좋겠어.

- **원본** (16.14초, 추천 5개): Max Payne 2: The Fall of Max Payne, BioShock 2, System Shock 2, Overlord: Raising Hell, Syndicate
  - 제외 3개 · 경고 3건
    - System Shock 2: 리뷰 요약 확인 불가
    - Syndicate: 리뷰 요약 확인 불가
    - Syndicate: 원화 가격 확인 불가
- **에이전트** (11.45초, 추천 4개): Portal 2, Half-Life 2, Half-Life, Batman: Arkham Asylum
  - 제외 2개 · 경고 0건

에이전트 타임라인:

```text
  0.00s  질문 분해     started
  1.40s  질문 분해     completed
  1.40s  에이전트 추론   started
  2.23s  게임 검색     started
  4.07s  게임 검색     completed · 후보 30개
  5.17s  하드웨어      started
  5.17s  가격        started
  6.04s  하드웨어      completed
  6.04s  가격        completed
  6.94s  리뷰 요약     started
  8.72s  리뷰 요약     completed
 11.04s  에이전트 추론   completed · 도구 호출 4회
 11.04s  조건 판정     completed · 통과 28개 중 4개 추천, 제외 2개
 11.04s  미디어       started
 11.44s  미디어       completed
```

#### 복합 조건 (데모용)

> RTX 3060, RAM 16GB PC를 사용하고 있어. 친구 한 명과 온라인으로 같이 할 수 있고, 공포 게임은 싫어. 3만 원 이하이면서 Steam 평가가 좋은 게임 3개만 추천해줘.

- **원본** (24.77초, 추천 3개): Overlord II, Portal 2, Mass Effect 3
  - 제외 20개 · 경고 0건
- **에이전트** (14.52초, 추천 3개): Portal 2, Stardew Valley, Call of Duty 4: Modern Warfare
  - 제외 19개 · 경고 0건

에이전트 타임라인:

```text
  0.00s  질문 분해     started
  1.31s  질문 분해     completed
  1.31s  에이전트 추론   started
  2.27s  게임 검색     started
  3.68s  게임 검색     completed · 후보 30개
  4.58s  가격        started
  4.58s  하드웨어      started
  4.78s  가격        completed
  8.55s  하드웨어      completed
  9.50s  리뷰 점수     started
  9.86s  리뷰 점수     completed
 10.62s  리뷰 요약     started
 12.45s  리뷰 요약     completed
 14.06s  에이전트 추론   completed · 도구 호출 5회
 14.06s  조건 판정     completed · 통과 11개 중 3개 추천, 제외 19개
 14.06s  미디어       started
 14.52s  미디어       completed
```
