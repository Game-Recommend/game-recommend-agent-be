# game-recommend-be 백엔드

경로와 명령은 저장소 루트를 기준으로 합니다.
프론트엔드는 [game-recommend-fe](https://github.com/Game-Recommend/game-recommend-fe)에서 개발합니다.

하드웨어·취향·인원 수·예산·플레이타임·플랫폼 조건을 자연어로 받아, 조건에 맞는 게임을 추천하는 FastAPI 서버입니다.

현재는 **역할별 도구 4개와 실행 파이프라인을 구현한 단계**입니다. 외부 API·LLM 어댑터는
아직 구현하지 않았습니다. 테스트에서는 가짜 연동을 주입해 흐름을 검증하며,
기본 서버의 `POST /recommend`는 연동을 설정하기 전까지 503을 반환합니다.

## 기술 구성

| 구분 | 현재 구성 |
| --- | --- |
| 런타임 | Python 3.12 이상 |
| HTTP 서버 | FastAPI, Uvicorn |
| 데이터 검증·설정 | Pydantic, pydantic-settings |
| HTTP 클라이언트 의존성 | `httpx2` (`pyproject.toml`에 선언) |
| 파이프라인 | 비동기 Python 오케스트레이터, 가격·사양 병렬 실행 |
| 개발 도구 | pytest, Ruff, Makefile |
| CI | GitHub Actions: PR 및 `main` 푸시 시 린트·테스트 |

의존성과 도구 설정은 [pyproject.toml](pyproject.toml), 실행 명령은
[Makefile](Makefile), 역할별 개발 범위는 [TEAM.md](TEAM.md)에서 관리합니다.

## 예상 질문

- **하드웨어**: "내 노트북이 i5-1240P, RAM 16GB, 내장그래픽인데 원활하게 할 수 있는 게임 중에서 평점 좋은 게임 추천해줘."
- **멀티플레이 + 인원**: "친구 4명이서 온라인으로 같이 할 게임을 찾고 있어. 경쟁보다는 협동 위주였으면 좋겠고 한 판이 너무 길지 않았으면 좋겠어."
- **가격 + 취향**: "지금 2만 원 이하로 살 수 있는 게임 중에서 스토리가 중요한 RPG 추천해줘. 턴제 게임은 별로 안 좋아해."
- **플레이타임 + 장르**: "취업 준비하면서 가볍게 할 게임을 찾고 있어. 한 번에 30분~1시간 정도 하기 좋고, 전체 플레이타임도 15시간을 넘지 않는 싱글 게임이면 좋겠어."
- **복합 조건 (데모용)**: "RTX 3060, RAM 16GB PC를 사용하고 있어. 친구 한 명과 온라인으로 같이 할 수 있고, 공포 게임은 싫어. 3만 원 이하이면서 Steam 평가가 좋은 게임 3개만 추천해줘."

## 파이프라인

```text
질문
  ↓
질문 분해 LLM → GameConditions
  ↓
Tool 1: IGDB 후보 검색·조건 필터링
  ├─ Tool 2: 가격 조회·예산 판정 ─────┐
  └─ Tool 3: 요구 사양 조회·호환성 판정 ┤ 병렬 실행
                                     ↓
                       ID 기준 병합·조건 충족 후보 선택
                                     ↓
                       Tool 4: 선택한 후보의 리뷰 요약
                                     ↓
                       최종 답변 LLM → 근거와 함께 응답
```

호출 순서는 `app/pipeline/orchestrator.py`가 결정하며 가격·사양은 `asyncio.gather()`로
동시에 실행합니다. LangGraph는 도입하지 않았습니다. 향후 사용자 응답을 기다리는
조건 완화·재검색이나 실행 상태 저장·재개가 필요할 때 검토합니다.

## 도구와 외부 연동의 역할

| 서비스 도구 | 하는 일 | 연동 구현 위치 / 예정 출처 |
| --- | --- | --- |
| `GameSearchTool` | 조건에 맞는 후보 조회·중복 제거 | `GameCatalogClient` / IGDB |
| `PriceTool` | 정규화된 원화 가격과 예산 비교 | `PriceClient` / Steam (`SteamStoreClient`); Steam에 없는 후보는 무료 게임 표 → CheapShark + Frankfurter 환율 (`CheapSharkClient`) |
| `HardwareTool` | 사양 평가 결과 정리, 사양 조건 없으면 생략 | `HardwareClient` / Steam (`SteamStoreClient`), Steam에 없는 후보는 PCGamingWiki (`PcGamingWikiClient`); 공통 메모리 규칙 + GPU·CPU LLM 판정 (`hardware_assessor.py`, `OpenAISpecJudge`) |
| `ReviewSummaryTool` | 선택된 후보의 리뷰 요약 요청 | `ReviewSummaryClient` / 리뷰 요약 API 또는 Steam 리뷰 + LLM |

`app/tools/`는 서비스 역할, `app/clients/`는 외부 연동을 담당합니다. 외부 제공자 수와 서비스
도구 수는 일치할 필요가 없습니다. 공급자별 `app/clients/*.py`는 현재 API 참고 문서이며,
실제 호출 어댑터는 `app/clients/contracts/`의 역할별 비동기 Protocol을 구현해야 합니다.
담당 파일과 역할별 테스트 명령은 [4인 개발 가이드](TEAM.md)에 정리되어 있습니다.

### 데이터와 실패 처리

- 후보와 결과는 `igdb_id`로 연결합니다. Steam 연결용 `steam_app_id`도 후보에 보관합니다.
- `steam_app_id`가 없는 후보만 폴백을 탑니다 (`app/clients/routing.py`). 가격은 무료 게임 표
  (`free_games.py`) → CheapShark USD 최저가 × Frankfurter 환율 순서이고, 사양은 PCGamingWiki입니다.
  두 폴백 모두 정규화한 게임명이 정확히 같은 결과만 인정하며, 못 찾으면 `unknown`입니다.
  환율을 받지 못하면 USD 가격을 원화로 내지 않습니다. 폴백 실패는 Steam 결과를 지우지 않습니다.
- 질문 조건은 온라인/로컬, 싱글/협동/경쟁, 전체 완료 시간/세션 시간, CPU·GPU·RAM,
  추천 개수를 구분합니다. 없는 조건은 추측하지 않습니다.
- 검색 어댑터는 명시된 필수 검색 조건을 검증한 후보를 우선순위순 반환해야 합니다.
  IGDB의 완료 시간을 세션 시간으로 대체하지 않습니다. 검색 단계에서 필수 조건을
  검증할 수 없는 게임은 충족 후보로 반환하지 않습니다.
- 가격·사양은 `met`(충족), `unmet`(미충족), `unknown`(확인 불가)로 구분합니다.
  사용자가 조건을 지정하지 않았을 때만 `skipped`(검사 생략)를 사용합니다.
- 예산이 없더라도 답변용 가격은 조회합니다. `0원` 예산은 무료 게임 조건입니다.
  USD를 그대로 원화 가격으로 취급하지 않으며 `PriceQuote`에는 검증한 원화 정수만 넣습니다.
- 하드웨어 어댑터는 요구 사양 수집과 사용자 PC 비교를 수행해야 합니다.
  요구 사양 문자열만으로 근거 없이 실행 가능하다고 판정하지 않습니다.
  사양 조건이 없어도 답변용 요구 사양은 조회해 `HardwareResult.requirement`에 담습니다.
  메모리는 숫자로 비교하고, GPU·CPU는 LLM 판정기(`OpenAISpecJudge`)가 후보 전체를 한 번에 판정합니다.
- 가격·사양 실패나 누락은 필수 조건 통과로 처리하지 않습니다. 한쪽 실패 시에도
  다른 쪽 결과는 보존합니다. 모든 조건 검사 후 추천 개수를 제한하고 리뷰를 요청합니다.
- 후보가 없으면 후속 도구를 생략하고 답변 생성 단계에 빈 후보와 이유를 전달합니다.
  조건은 임의로 완화하지 않습니다. 리뷰 실패 시 요약 없이 후보와 경고를 전달합니다.
- 각 단계의 제한 시간은 기본 30초이며 생성자에서 변경할 수 있습니다.
  질문 분해·검색·최종 답변 실패는 HTTP 502, 연동 미설정은 503입니다.

현재 순위는 검색 어댑터가 반환한 순서를 유지합니다. 리뷰 점수 기반 재정렬,
자동 재시도, 호출 제한, 캐시, 대화 메모리는 아직 구현하지 않았습니다.

## 외부 연동 예정 모듈

아래 파일은 호출 구현 없이 연동 참고 사항만 담고 있습니다.

| 모듈 | 예정 역할 |
| --- | --- |
| [igdb.py](app/clients/igdb.py) | 후보 게임 검색·필수 조건 검증 |
| [steam_reviews.py](app/clients/steam_reviews.py) | Steam 리뷰 수집 |

Steam에 없는 후보용 폴백은 구현되어 있습니다.

| 모듈 | 역할 |
| --- | --- |
| [routing.py](app/clients/routing.py) | `steam_app_id` 유무로 Steam·폴백 클라이언트 분기·병합 |
| [cheapshark.py](app/clients/cheapshark.py) | 무료 게임 표 확인 후 CheapShark USD 최저가를 원화로 변환 |
| [exchange_rate.py](app/clients/exchange_rate.py) | Frankfurter USD→KRW 환율 (키 불필요, 1시간 캐시) |
| [free_games.py](app/clients/free_games.py) | 자체 런처 무료 게임 수동 목록 (LoL, 발로란트 등) |
| [pcgamingwiki.py](app/clients/pcgamingwiki.py) | PCGamingWiki `System requirements` 템플릿에서 PC 요구 사양 조회, Steam과 같은 판정 규칙 적용 (키 불필요) |

## 시작하기

Python 3.12 이상이 필요합니다.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env    # 실제 API 어댑터 연동 시 키 채우기
make run                # http://127.0.0.1:8000/health
```

`python3`가 Python 3.12 이상인지 먼저 확인하세요. Makefile은 `.venv/bin/python`이
있으면 사용하고, 없으면 PATH의 `python3`를 사용합니다. 다른 인터프리터는
`make run PY=python3.12`처럼 지정할 수 있습니다.

서버 실행 후 다음 경로에서 확인할 수 있습니다.

- 생존 확인: `http://127.0.0.1:8000/health`
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI 스키마: `http://127.0.0.1:8000/openapi.json`

### 환경 변수

[app/config.py](app/config.py)의 `Settings`는 환경 변수와 루트의 `.env`를 읽습니다.
현재 등록된 키의 기본값은 모두 빈 문자열이며, 서버 시작에 실제 키는 필요하지 않습니다.
단, `API_KEY`가 비어 있으면 `/recommend`는 503을 돌려줍니다.

| 변수 | 연동 시 용도 |
| --- | --- |
| `API_KEY` | `/recommend` 호출용 공유 비밀. 프론트 서버 환경 변수에 같은 값을 두고 `X-API-Key` 헤더로 보낸다 |
| `IGDB_CLIENT_ID` | Twitch 개발자 앱 클라이언트 ID |
| `IGDB_CLIENT_SECRET` | Twitch 개발자 앱 클라이언트 시크릿 |
| `OPENAI_API_KEY` | OpenAI API 키. GPU·CPU 사양 판정에 쓴다 |
| `OPENAI_MODEL` | 사양 판정 모델. 기본값 `gpt-4o-mini` |

키 목록의 기준은 [.env.example](.env.example)입니다. 사양 판정은 OpenAI를 쓰며,
질문 가공·리뷰 요약·최종 답변의 LLM 키는 각 담당자가 구현하면서 추가합니다. 현재 앱에는 설정을 읽어 어댑터를 자동으로 조립하는 코드가
없으므로, 키를 채우는 것만으로 추천 기능이 활성화되지는 않습니다.

### 개발·검증 명령

| 명령 | 하는 일 |
| --- | --- |
| `make run` | 개발 서버 (코드 변경 시 자동 재시작) |
| `make lint` | ruff 검사 |
| `make test` | pytest |
| `make test-query-processing` | 질문 조건 모델 테스트 |
| `make test-igdb` | 후보 검색 도구 테스트 |
| `make test-price-hardware` | 가격·사양·최종 답변 테스트 |
| `make test-final-answer` | 최종 답변 연결 테스트 |
| `make test-reviews` | 리뷰 요약 도구 테스트 |
| `make test-integration` | 파이프라인·병렬 실행·HTTP API 테스트 |

테스트 옵션은 `make test ARGS="-q"`처럼 전달합니다. `make test-llm`은
`make test-query-processing`의 호환용 별칭입니다. 테스트는 역할별 가짜 연동을
사용하며 실제 외부 API 호출이나 LLM 출력 품질은 검증하지 않습니다.

## HTTP API

### `GET /health`

```bash
curl http://127.0.0.1:8000/health
```

응답은 `200 OK`와 `{"status":"ok"}`입니다. 서버 생존 확인용이며 추천 연동 준비
상태를 의미하지 않습니다.

### `POST /recommend`

```bash
curl -X POST http://127.0.0.1:8000/recommend \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $API_KEY" \
  -d '{"question":"3만 원 이하 협동 게임 3개 추천해줘"}'
```

`X-API-Key` 헤더는 필수이며 환경 변수 `API_KEY`와 같아야 합니다. 이 키는 프론트 **서버**의
환경 변수에만 두고 브라우저로 내리지 않습니다. 브라우저는 프론트 서버(API 라우트·서버 액션)를 거쳐
BE를 호출해야 BE 주소와 키가 노출되지 않습니다. `/health`는 키 없이 열려 있습니다.

`question`은 필수 문자열이며 1~5,000자이고 공백 외 문자를 포함해야 합니다.
추천 개수는 질문 분해 결과의 `recommendation_count`로 전달되며 기본 3개, 범위 1~20개입니다.

연동을 주입한 뒤 성공하면 다음 필드를 반환합니다.

| 필드 | 내용 |
| --- | --- |
| `conditions` | 질문에서 추출한 `GameConditions` |
| `games` | 추천 후보 목록. 각 항목은 `game`, `price`, `hardware`, `review`를 포함 |
| `excluded_games` | 가격·사양 검사에서 제외한 후보 목록 |
| `warnings` | 조회 실패·정보 누락·충족 후보 없음 등의 안내 |
| `answer` | 최종 답변 생성기가 반환한 문자열 |

`excluded_games`에는 추천 개수 제한으로 선택되지 않은 충족 후보는 포함하지 않습니다.
정확한 중첩 필드는 [응답 모델](app/schemas/recommendation.py)과 Swagger UI에서 확인하세요.

| 상태 코드 | 의미 |
| --- | --- |
| `200` | 추천 흐름 완료. 충족 후보가 없더라도 답변 생성이 성공하면 반환 |
| `401` | `X-API-Key` 헤더가 없거나 `API_KEY`와 다름 |
| `422` | 요청 검증 실패 (연동이 주입된 상태에서 검증 가능) |
| `502` | 질문 분해·게임 검색·최종 답변 생성의 실패 또는 시간 초과 |
| `503` | `API_KEY` 미설정 또는 `app.state.recommender` 미설정 |

기본 서버에서 위 추천 요청을 보내면 다음 오류를 반환합니다.

```json
{"detail":"추천 서비스의 외부 연동이 설정되지 않았습니다."}
```

## 배포 설정

- Root Directory: 저장소 루트 (`.`)
- 앱: FastAPI
- Vercel 진입점 선언: `app.main:app` (`pyproject.toml`의 `tool.vercel.entrypoint`)
- 환경 변수: `.env.example`을 기준으로 Vercel 프로젝트에 설정

`app/main.py`에는 CORS 미들웨어가 없습니다. 브라우저가 BE를 직접 부르지 않고 프론트 서버가
`X-API-Key`를 붙여 호출하는 구성을 전제로 하므로 CORS 허용이 필요 없습니다. BE 배포 주소는
저장소·문서에 적지 않고 프론트 서버 환경 변수로만 전달합니다.
[GitHub Actions](.github/workflows/ci.yml)는 린트·테스트만 실행하며 배포 단계는 없습니다.
CI 성공을 머지 조건으로 사용하려면 GitHub 브랜치 규칙을 설정합니다.

## 실제 연동 연결하기

질문 가공 담당자는 `app/pipeline/query_processing/`에서 `QueryParser.parse()`를,
가격·하드웨어·최종 답변 담당자는 `app/pipeline/final_answer/`에서 `Answerer.generate()`를
각각 별도 구현체로 작성합니다.
LLM 결과는 `GameConditions`로 검증하고, 최종 답변은 전달한 후보와 근거만 사용해야 합니다.
아래 함수의 인자들은 실제로 구현한 어댑터 인스턴스입니다. 키 설정만으로는 연결되지 않습니다.

```python
from app.main import app
from app.pipeline.orchestrator import RecommendationOrchestrator
from app.tools.game_search import GameSearchTool
from app.tools.hardware import HardwareTool
from app.tools.price import PriceTool
from app.tools.review_summary import ReviewSummaryTool


def configure_recommender(parser, catalog, prices, hardware, reviews, answerer):
    app.state.recommender = RecommendationOrchestrator(
        parser=parser,
        game_search=GameSearchTool(catalog),
        price=PriceTool(prices),
        hardware=HardwareTool(hardware),
        review_summary=ReviewSummaryTool(reviews),
        answerer=answerer,
    )
```

서버 시작 시 어댑터를 조립해 주입하고, HTTP 클라이언트 수명 관리도 함께 구현합니다.
역할별 테스트 대역은 `tests/<담당 영역>/fakes.py`에 있고,
통합 조립 예시는 `tests/integration/conftest.py`에 있습니다.

## 디렉터리

```text
.github/workflows/ci.yml    Python 3.12 린트·테스트
.env.example               외부 연동용 환경 변수 예시
pyproject.toml             의존성·빌드·pytest·Ruff·Vercel 설정
Makefile                   개발 서버·검증 명령
TEAM.md                    역할별 담당 파일·연결 계약
app/
├─ main.py                  FastAPI 앱
├─ config.py                .env 설정
├─ api/
│  ├─ routes.py             /health, /recommend
│  └─ dependencies.py       조립한 추천 파이프라인 주입
├─ pipeline/
│  ├─ query_processing/     질문 가공 담당
│  │  ├─ conditions.py      질문 조건 모델
│  │  └─ parser.py          질문 분해 LLM 계약
│  ├─ final_answer/         가격·하드웨어·최종 답변 담당
│  │  └─ answerer.py        최종 답변 LLM 계약
│  └─ orchestrator.py       공통: 실행 순서·병렬 처리·병합·실패 처리
├─ tools/
│  ├─ game_search.py        Tool 1
│  ├─ price.py              Tool 2
│  ├─ hardware.py           Tool 3
│  └─ review_summary.py     Tool 4
├─ clients/
│  ├─ contracts/            catalog.py · price.py · hardware.py · reviews.py
│  ├─ igdb.py               IGDB API 참고 문서
│  ├─ steam_store.py        가격·하드웨어 담당: Steam 상세 API 클라이언트 (가격·사양)
│  ├─ hardware_assessor.py  가격·하드웨어 담당: Steam·폴백 공통 사양 판정 규칙
│  ├─ hardware_judge.py     가격·하드웨어 담당: GPU·CPU 판정기 계약과 OpenAI 구현
│  ├─ routing.py            가격·하드웨어 담당: steam_app_id 유무로 Steam·폴백 분기
│  ├─ cheapshark.py         가격·하드웨어 담당: 비Steam 가격 폴백 (무료 표 → CheapShark)
│  ├─ exchange_rate.py      가격·하드웨어 담당: Frankfurter USD→KRW 환율
│  ├─ free_games.py         가격·하드웨어 담당: 자체 런처 무료 게임 표
│  ├─ pcgamingwiki.py       가격·하드웨어 담당: 비Steam 요구 사양 폴백
│  └─ steam_reviews.py      리뷰 담당: Steam 리뷰 API
└─ schemas/
   ├─ game.py               IGDB 담당: 후보 모델
   ├─ price.py              가격·하드웨어 담당: 가격 모델
   ├─ hardware.py           가격·하드웨어 담당: 사양 모델
   ├─ review.py             리뷰 담당: 요약 모델
   ├─ common.py             공통: 조건 판정 상태
   └─ recommendation.py     공통: 추천 근거·HTTP 요청/응답
tests/
├─ query_processing/        질문 가공 담당 테스트와 대역
├─ igdb/                    IGDB 담당 테스트와 대역
├─ price_hardware/          가격·하드웨어 담당 테스트와 대역
│  └─ final_answer/         같은 담당자의 최종 답변 연결 테스트와 대역
├─ reviews/                 리뷰 담당 테스트와 대역
└─ integration/             전체 흐름·병렬 실행·API 테스트
```
