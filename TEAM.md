# 역할별 개발 가이드 (에이전트 & Tool calling 전환판)

경로는 저장소 루트 기준입니다. 이 저장소는 [game-recommend-be](https://github.com/Game-Recommend/game-recommend-be)를
복사해, 고정 파이프라인을 **LangChain 에이전트가 Tool을 골라 호출하고 최종 답변까지 쓰는 구조**로 바꾸는
작업 공간입니다. 프론트는 [game-recommend-agent-fe](https://github.com/Game-Recommend/game-recommend-agent-fe)입니다.
발표는 2026-09-18(금)입니다.

## 전환 원칙

- **팀원 모듈은 그대로 둡니다.** `app/clients/*`, `app/tools/*`, 질문 가공(`app/pipeline/query_processing/`)은
  손대지 않습니다. 에이전트 계층 `app/agent/`가 기존 서비스 도구의 `run()`을 얇게 감쌉니다.
- **Tool 하나는 동사 하나입니다.** 기능이 더 필요하면 Tool을 하나 더 만듭니다. `action` 인자로 여러 기능을
  묶지 않습니다.
- **인자는 `igdb_id` 목록(배치)입니다.** 예산·사용자 사양·추천 개수 같은 기준값은 LLM이 넘기지 않고
  러너가 `AgentContext.conditions`(질문 분해 결과)로 주입합니다. `search_games`만 검색 조건을 인자로 받습니다.
- **결과는 두 갈래입니다.** LLM에는 압축 JSON(dict)만 돌려주고, 응답용 전체 pydantic 모델은
  `CandidateStore`(`ctx.store`)에 쌓습니다. 응답 형태(`RecommendationResponse`)는 기존과 같아 FE가 바뀌지 않습니다.
- **Tool 본문은 `ctx.run_stage()`로 감쌉니다.** 진행 이벤트(SSE `stage`), 30초 제한, 실패의 오류 JSON 변환을
  공통으로 처리합니다. 실패해도 예외를 올리지 않고 에이전트가 계속 진행합니다.
- **docstring이 곧 LLM이 읽는 사용 설명서입니다.** 언제 부르고 언제 부르지 말지, 결과 필드의 뜻, 비용을 적습니다.
- **LangChain은 에이전트 계층에만 씁니다.** 팀원 모듈을 LangChain으로 다시 쓰지 않습니다.
- 원본의 고정 파이프라인(오케스트레이터·최종 답변 LLM)은 이 저장소에서 제거했습니다. 전후 비교는 원본
  `game-recommend-be`로 합니다.

## 구조

```text
POST /recommend
  ↓
LLMQueryParser (질문 가공, 그대로) → GameConditions ─── 기준값을 Tool에 주입
  ↓
AgentRecommender (app/agent/runner.py, LangChain create_agent)
  │  시스템 프롬프트: app/agent/prompts.py
  │  루프: LLM → tool_calls(같은 턴 병렬) → ToolNode → LLM … → RecommendationDraft
  ├─ search_games      app/agent/tools/search.py    → GameSearchTool.run    (IGDB 담당)
  ├─ get_prices        app/agent/tools/price.py     → PriceTool.run         (가격·하드웨어 담당, 참조 예시)
  ├─ assess_hardware   app/agent/tools/hardware.py  → HardwareTool.run      (가격·하드웨어 담당)
  ├─ get_review_scores app/agent/tools/review_score.py → ReviewScoreTool.run (리뷰 담당)
  └─ summarize_reviews app/agent/tools/reviews.py   → ReviewSummaryTool.run (리뷰 담당)
  ↓
러너 후검증: 후보에 있는 id · 가격/사양 판정 통과 · 요청 개수 이하 → 위반 시 거부 사유를 붙여 1회 재호출
안전망: 추천 후보 중 가격·사양·리뷰를 조회하지 않은 게임은 러너가 직접 조회
  ↓
MediaTool (에이전트 밖 후처리) → RecommendationResponse (기존과 같은 형태)
```

`app/agent/context.py`의 `AgentContext`(요청 컨텍스트), `CandidateStore`(후보·판정 저장소), `ToolSet`(서비스
도구 묶음)이 공통 계약입니다. `app/assembly.py`가 `.env`로 `ToolSet`을 만들고 모드에 따라 추천기를 고릅니다.

## 담당 파일과 할 일

역할은 기존 4개 그대로입니다. 각자 담당 영역이 "클라이언트 + 서비스 도구"에서 "+ Tool 정의 파일" 한 겹
늘어납니다. Tool 파일의 뼈대는 통합 담당이 만들어 두었으니, 담당자는 **description·압축 출력·테스트·도메인
확장**을 맡습니다. 각자 자기 Tool을 발표합니다.

### 공통 (통합 담당)

| 상태 | 파일 | 내용 |
| --- | --- | --- |
| 완료 | `app/agent/context.py` | `ToolSet`, `AgentContext.run_stage()/optional()`, `CandidateStore`(resolve·evaluate·validate_draft·build_evidence) |
| 완료 | `app/agent/runner.py` | LangGraph `StateGraph` 조립(`create_agent`는 서브그래프 노드), 후검증·재시도, 안전망, 미디어 후처리, `stream()`, Mermaid 그래프 |
| 완료 | `app/agent/schemas.py` | 최종 출력 `RecommendationDraft` |
| 완료 | `app/agent/tools/__init__.py` | `build_tools()` Tool 목록 |
| 완료 | `app/agent/progress.py` | 진행 콜백·`PipelineStageError`·`stream_progress()`·`Recommender` 계약 |
| 완료 | `app/config.py`, `app/assembly.py` | `OPENAI_AGENT_MODEL`(비면 `OPENAI_MODEL`), 에이전트 조립 |
| 완료 | `.env.example`, `app/__init__.py` | LangSmith 변수는 `LANGSMITH_TRACING`·`LANGSMITH_API_KEY`·`LANGSMITH_PROJECT` 세 개이고 `.env.example`에 주석으로 있다. LangChain이 환경 변수만 보고 켜므로 `Settings`에는 넣지 않았다. `.env`는 `app/__init__.py`의 `load_dotenv()`가 app 패키지 import 시점에 올린다 |
| 완료 | `tests/agent/` | 대본 모델(`ScriptedChatModel`)로 루프·후검증·안전망·SSE 검증 |
| 완료 | Tool 5개로 늘어난 계약 반영 | `get_review_scores` 추가에 맞춰 README·TEAM.md의 Tool 목록·SSE 단계명(`리뷰 점수`)·`ToolSet`을 맞췄다. FE도 `AGENT_TOOL_STAGES`에 `리뷰 점수`를 넣어 반영했다(agent-fe `5b41bc7`) |
| 완료 | 실제 키로 예상 질문 5개 전후 비교 | 요약은 README `## 전후 비교`, 질문별 타임라인·원시 기록·재실행 방법은 `evals/agent_questions/`다. 같은 턴 병렬 호출과 안전망이 타임라인에 그대로 보인다 |
| 완료 | Vercel 프로젝트·자동 배포 | GitHub 연동이라 저장소에 `vercel.json`이 없다. `main`에 머지하면 프로덕션이 자동 배포된다 |
| 완료 | 패키지 크기 확인 | dev 의존성(37MB)을 뺀 약 84MB로 서버리스 250MB 제한에 여유. 큰 순서로 `openai` 24MB, `langsmith` 9.9MB, `langchain_core` 5.8MB. 로컬(macOS·3.14) 측정이라 Vercel(Linux·3.12)과 컴파일 휠 크기가 다를 수 있다 |
| 완료 | Vercel 환경 변수 확인 | 필수는 `API_KEY`·`OPENAI_API_KEY`·`IGDB_CLIENT_ID`·`IGDB_CLIENT_SECRET` 네 개이고, 하나라도 비면 `/recommend`가 503이다. `STEAMGRIDDB_API_KEY`는 없어도 동작하며 로고·배너만 빠진다. `OPENAI_MODEL`·`OPENAI_AGENT_MODEL`은 기본값(`gpt-4o-mini`)이 있어 등록하지 않는다. 빈 값으로 등록하면 기본값을 덮어써 모델명 없이 호출되므로, `.env.example`을 통째로 붙여넣지 않는다. 배포 URL은 배포 보호(302)라 외부에서 `/health`를 확인할 수 없고, 함수 로그의 `missing settings` 경고로 본다 |

### 질문 가공 담당

파서(`LLMQueryParser`)는 0단계로 그대로 씁니다. 새로 **에이전트 프롬프트 전체**를 맡습니다.

| 파일 | 할 일 |
| --- | --- |
| `app/agent/prompts.py` | `AGENT_SYSTEM`(도구 사용 순서·답변 규칙·실패 처리) 다듬기. 답변 규칙은 원본의 최종 답변 프롬프트에서 옮겨 온 초안이다 |
| `app/agent/prompts.py` | `build_user_input()`(질문 + 추출 조건 + 검색 인자 JSON), `build_rejection()`(후검증 거부 문구) |
| `tests/agent/test_prompts.py` (신규) | 입력 구성에 조건·검색 인자가 빠지지 않는지, 거부 문구에 문제 목록이 들어가는지 |
| 평가 표 (Notion/README) | 질문 유형별(복합 조건, 가격만, 사양만, 특정 게임, 조건 없음) 실제 Tool 호출 순서·횟수와 답변 품질을 표로 기록. LangSmith 추적을 켜면 호출 기록이 그대로 남는다 |

주의: Tool 이름(`search_games`, `get_prices`, `assess_hardware`, `summarize_reviews`)과 최종 출력 이름
(`RecommendationDraft`)은 코드와 같아야 합니다. 프롬프트를 바꾸면 `make test-agent`로 확인합니다.

### IGDB 담당

| 파일 | 할 일 |
| --- | --- |
| `app/agent/tools/search.py` | `search_games` docstring(언제 부르고 언제 부르지 말지), `SearchGamesArgs` 필드 설명, `compact_candidate()` 출력 필드 결정(플랫폼 목록 길이, 소개 200자 등) |
| `app/agent/tools/search.py` | `search_candidates()`가 인자를 `GameConditions`로 합칠 때 별칭(모바일, 한국어 장르명)이 `igdb.py`의 `normalize()`와 맞는지 확인 |
| `tests/igdb/test_search_tool.py` (신규) | `FakeCatalog`로 인자→조건 변환, 압축 출력, store 저장 검증 (`tests/agent/test_tools.py`의 검색 테스트를 옮겨도 된다) |
| 여유가 있으면 `lookup_game` | "엘든링 내 PC에서 돌아가?"처럼 게임 이름으로 묻는 질문용. `igdb.py`에 이름 검색을 추가하고 `app/agent/tools/search.py`에 두 번째 Tool로 정의한 뒤 `build_tools()`에 등록 |

### 가격·하드웨어·미디어 담당 (통합 담당 겸임)

| 파일 | 할 일 |
| --- | --- |
| `app/agent/tools/price.py` | 완료. 다른 Tool 파일의 참조 예시 |
| `app/agent/tools/hardware.py` | 완료. `compact_spec()` 표현 다듬기 |
| 미디어 | 변경 없음. 에이전트 밖 후처리(`runner._finalize`) |
| 최종 답변 | 원본의 `final_answer/`는 제거. 답변 규칙은 `app/agent/prompts.py`(질문 가공 담당)로 이관 |

### 리뷰 담당

| 파일 | 할 일 |
| --- | --- |
| `app/agent/tools/review_score.py` | 완료. `get_review_scores`(Steam 리뷰 통계)는 후보 선별용 수치, `summarize_reviews`는 카드용 문장으로 쓰임을 나눴다. 결과는 `CandidateStore`에 담지 않아 응답 본문에 나오지 않는다 |
| `app/agent/tools/reviews.py` | `summarize_reviews` docstring 다듬기. "최종 추천 후보에만" 원칙과 비용 안내 유지 |
| `app/agent/tools/reviews.py` | 에이전트가 "평가 좋은 게임" 조건에 쓸 수 있는 압축 필드 검토(긍정 비율, `review_score_desc`). `ReviewSummary` 모델 확장은 리뷰 담당 결정이며, 바꾸면 `schemas/review.py` 소비자(FE 카드)와 조율 |
| `app/clients/steam_reviews.py` | 게임을 순차 처리해 3개면 3배 느리다. `asyncio.gather`로 게임별 병렬 처리 검토(리뷰 담당 모듈이므로 리뷰 담당이 결정) |
| `tests/reviews/test_reviews_tool.py` (신규) | `FakeReviews`로 압축 출력, `steam_app_id` 없는 게임의 `summary: null`, 실패 시 오류 JSON 검증 |

## Tool 정의 규약

참조 예시는 `app/agent/tools/price.py`입니다. 새 Tool은 이 순서로 씁니다.

```python
STAGE = "가격"                       # SSE stage 이름. FE가 아는 단계명과 같게 유지한다

async def fetch_prices(ctx: AgentContext, igdb_ids: list[int]) -> dict:   # 실제 일. 테스트 대상
    games = ctx.store.resolve(igdb_ids)                   # 모르는 id면 UnknownCandidateError → LLM에 오류 JSON
    results = await ctx.tools.price.run(games, ctx.conditions.max_price_krw)   # 팀원 도구 그대로
    ctx.store.prices.update(results)                      # 응답용 전체 모델
    return {"budget_krw": ..., "prices": [compact_price(r) for r in ...]}       # LLM용 압축본

@tool("get_prices")
async def get_prices(igdb_ids: list[int], runtime: ToolRuntime[AgentContext]) -> str:
    """LLM이 읽는 설명. 언제 부르는지, 인자 규칙, status 뜻, 부르지 말아야 할 때."""
    ctx = runtime.context
    return await ctx.run_stage(STAGE, fetch_prices(ctx, igdb_ids))
```

체크리스트

- 이름은 동사형 스네이크 케이스, 인자는 `igdb_ids: list[int]` (검색만 예외).
- docstring에 (1) 언제 부르는지 (2) 무엇을 넘기는지 (3) 결과 필드와 status 뜻 (4) 부르지 말아야 할 때·비용을 적는다.
- 압축 출력에는 LLM이 판단에 쓸 것만 넣는다. URL·원문 HTML·긴 소개는 넣지 않는다.
- 기준값은 `ctx.conditions`에서 읽는다. LLM에게 다시 넘기게 하지 않는다.
- 실패는 `run_stage`가 처리한다. Tool 안에서 예외를 삼키지 않는다.
- `build_tools()`에 등록하고 `tests/agent/test_tools.py::test_tool_schemas_hide_runtime_and_server_criteria`가 통과하는지 본다.

## 연결 계약

기존 역할별 계약(Protocol)은 그대로입니다. 에이전트 계층은 그 위에 다음 계약을 더합니다.

| 항목 | 정의 | 위치 |
| --- | --- | --- |
| `ToolSet` | 서비스 도구 묶음. `game_search`, `price`, `hardware`, `review_summary`, `review_score`, `media` | `app/agent/context.py` |
| `AgentContext` | 요청 컨텍스트. `conditions`, `store`, `tools`, `progress`, `run_stage()`, `optional()` | `app/agent/context.py` |
| `CandidateStore` | `add_candidates()`, `resolve(ids)`, `prices/hardware/reviews/media` dict, `warn()`, `validate_draft()`, `build_evidence()` | `app/agent/context.py` |
| Tool 반환 | 성공: 압축 dict → JSON 문자열. 실패: `{"error": "..."}` (+ warnings). 모르는 id: `{"error": "후보 목록에 없는 igdb_id: [...]"}` | `run_stage()` |
| `RecommendationDraft` | `recommended_igdb_ids`, `answer`. 러너가 검증한다 | `app/agent/schemas.py` |
| SSE 단계명 | 질문 분해, 에이전트 추론, 게임 검색, 가격, 하드웨어, 리뷰 점수, 리뷰 요약, 조건 판정, 미디어 | `runner.py`, 각 Tool의 `STAGE` |
| 리뷰 점수 저장 | `get_review_scores` 결과는 `CandidateStore`에 담지 않는다. 에이전트 판단 전용이라 응답 본문·안전망에 없다 | `app/agent/tools/review_score.py` |

## 작업 순서 (9/16 ~ 9/18)

1. **9/16 오전 (통합)** 이 뼈대 PR을 머지한다. 나머지 셋은 `.venv`를 새로 만들고(`pip install -e ".[dev]"`)
   `make test-agent`가 통과하는지, `make graph`가 그래프를 내는지 확인한다.
2. **9/16 오후 (각자)** 자기 Tool 파일의 docstring·압축 출력·테스트 PR. 질문 가공 담당은 시스템 프롬프트 초안 PR.
3. **9/17 (전원)** 실제 키로 README 예상 질문 5개를 이 저장소(에이전트)와 원본 `game-recommend-be`(고정
   파이프라인)로 각각 실행해 Tool 호출 순서·횟수·지연·답변을 기록한다. 질문 가공 담당은 유형별 호출 표를 만든다. 발표 자료.
4. **9/18** 발표. 각자 자기 Tool, 통합 담당은 그래프와 루프·후검증, 질문 가공 담당은 프롬프트 개선 과정.

## PR 규칙과 테스트 명령

- 브랜치는 `feat/<역할>-tool`처럼 만들고 PR로 `main`에 머지합니다. CI(린트·테스트·gitleaks)가 통과해야 합니다.
- 자기 Tool 파일과 자기 테스트 디렉터리만 고칩니다. `app/agent/context.py`·`runner.py`·`prompts.py`의 계약을 바꿔야
  하면 통합 담당과 먼저 맞춥니다.
- `.env`와 키는 커밋하지 않습니다. LangSmith 키도 마찬가지입니다.

```bash
make test-agent ARGS="-q"          # 에이전트 계층 (OpenAI 없이 대본 모델로)
make test-igdb ARGS="-q"           # 역할별 기존 명령은 그대로
make test-price-hardware ARGS="-q"
make test-reviews ARGS="-q"
make test-query-processing ARGS="-q"
make test-integration ARGS="-q"    # 조립·API·SSE
make test ARGS="-q"
make lint
make graph                         # Mermaid 그래프 출력
.venv/bin/python -m app.assembly "3만 원 이하 협동 게임 3개 추천해줘"   # 실제 키로 전체 흐름
```

대본 모델로 루프를 테스트하는 방법은 `tests/agent/fakes.py`와 `tests/agent/test_runner.py`를 참고합니다.
`search(...)`, `checks([...])`, `reviews([...])`, `draft([...])`로 AIMessage 대본을 만들면 실제 OpenAI 호출 없이
Tool 선택·병렬 호출·후검증을 검증할 수 있습니다.
