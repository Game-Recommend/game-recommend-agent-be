# game-recommend-app

하드웨어·취향·인원 수·예산·플레이타임·플랫폼 조건을 자연어로 받아, 조건에 맞는 게임을 추천하는 FastAPI 서버입니다.

## 예상 질문

- **하드웨어**: "내 노트북이 i5-1240P, RAM 16GB, 내장그래픽인데 원활하게 할 수 있는 게임 중에서 평점 좋은 게임 추천해줘."
- **멀티플레이 + 인원**: "친구 4명이서 온라인으로 같이 할 게임을 찾고 있어. 경쟁보다는 협동 위주였으면 좋겠고 한 판이 너무 길지 않았으면 좋겠어."
- **가격 + 취향**: "지금 2만 원 이하로 살 수 있는 게임 중에서 스토리가 중요한 RPG 추천해줘. 턴제 게임은 별로 안 좋아해."
- **플레이타임 + 장르**: "취업 준비하면서 가볍게 할 게임을 찾고 있어. 한 번에 30분~1시간 정도 하기 좋고, 전체 플레이타임도 15시간을 넘지 않는 싱글 게임이면 좋겠어."
- **복합 조건 (데모용)**: "RTX 3060, RAM 16GB PC를 사용하고 있어. 친구 한 명과 온라인으로 같이 할 수 있고, 공포 게임은 싫어. 3만 원 이하이면서 Steam 평가가 좋은 게임 3개만 추천해줘."

## 파이프라인

```text
질문
 ├─ 1. 질문 가공 (LLM)       자연어 → GameConditions
 ├─ 2. 도구 호출
 │    ├─ IGDB               장르·인원 수·플레이타임·플랫폼으로 후보 찾기
 │    ├─ Steam              원화 가격 · PC 사양 · 리뷰
 │    ├─ CheapShark         다른 스토어 최저가 (USD)
 │    ├─ RAWG               PC 사양 보조
 │    └─ 리뷰 요약 (LLM)     리뷰 본문 → 한줄평
 └─ 3. 최종 답변 (LLM)       게임 정보 + 한줄평 + 추천 이유
```

답변 뒤 이어지는 추가 질문을 대화 메모리로 받는 것은 선택 과제로 둡니다.

## 외부 API

| API | 용도 | 인증 | 알아둘 점 |
| --- | --- | --- | --- |
| [IGDB](https://api-docs.igdb.com/) | 후보 게임 필터링 | Twitch 앱 토큰 | 초당 4요청. 플레이타임은 `game_time_to_beats`, 온라인 협동 인원은 `multiplayer_modes` |
| Steam 스토어 | 원화 가격 · PC 사양 · 리뷰 | 없음 | appid로 조회. `cc=kr`이면 가격이 원화 ×100 단위, 사양은 HTML 문자열 |
| [CheapShark](https://apidocs.cheapshark.com/) | 스토어별 최저가 | 없음 | 가격이 USD. User-Agent 헤더가 없으면 거부 |
| [RAWG](https://rawg.io/apidocs) | PC 사양 보조 | API 키 | |

엔드포인트와 응답 필드는 `app/tools/` 각 모듈 상단에 정리해 두었습니다.

## 시작하기

Python 3.12 이상이 필요합니다.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env    # IGDB·RAWG 키 채우기
make run                # http://127.0.0.1:8000/health
```

| 명령 | 하는 일 |
| --- | --- |
| `make run` | 개발 서버 (코드 변경 시 자동 재시작) |
| `make lint` | ruff 검사 |
| `make test` | pytest |

## 디렉터리

```text
app/
├─ main.py                  FastAPI 앱
├─ config.py                .env 설정
├─ api/routes.py            HTTP 엔드포인트
├─ pipeline/
│  ├─ conditions.py         GameConditions — 1단계 출력이자 2단계 입력
│  ├─ query_parser.py       1단계 질문 가공
│  ├─ review_summarizer.py  리뷰 요약
│  └─ answerer.py           3단계 최종 답변
└─ tools/                   IGDB · Steam · CheapShark · RAWG
tests/
```
