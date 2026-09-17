# 예상 질문 5개 전후 비교 실측

2026-09-17 측정. 루트 [README](../../README.md)의 `## 예상 질문` 5개를 원본
[game-recommend-be](https://github.com/Game-Recommend/game-recommend-be)(고정 파이프라인)와 이 저장소
(에이전트)로 각각 한 번씩 실행했다. 두 저장소 모두 `gpt-4o-mini` 기본값이고, 원시 기록은
[runs/2026-09-17](runs/2026-09-17)에 있다.

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
