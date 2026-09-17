# 에이전트 엔드투엔드 평가

자연어 질문 100개를 실제 키로 끝까지 실행해, **사용자가 말한 필수 조건을 추천 결과가 지켰는지**
기계로 검증하는 평가셋이다. 문항은 [questions.md](questions.md), 실행 데이터는
[dataset.json](dataset.json), 최초 실측은 [REPORT.md](REPORT.md), 원시 기록은 [runs/](runs)에 있다.

평가 대상은 `AgentRecommender`(`app/agent/runner.py`)와 그 아래 전부다. 질문 분해, IGDB 검색,
가격·사양 판정, 리뷰, 최종 답변이 모두 들어간다. `evals/parser_conditions/`가 질문 분해만
떼어 보는 것과 대비된다.

**실제 외부 API와 LLM을 부른다.** 질문 하나에 약 14초와 LLM 비용 $0.006이 들고, IGDB·Steam
응답이 바뀌면 추천도 바뀐다. CI에서는 돌리지 않는다.

## 정답 없이 채점하는 방법

이 평가셋에는 "정답 추천 목록"이 없다. 열린 추천 질문 100개의 정답을 사람이 손으로 라벨링할 수
없기 때문이다. 대신 **응답만 보고 검증할 수 있는 조건**을 기대값으로 둔다.

| 질문 | 기계로 검증하는 것 |
| --- | --- |
| "3만 원 이하 게임 추천해줘" | 추천된 게임의 `price.quote.amount_krw`가 모두 30000 이하인가 |
| "게임 3개만 추천해줘" | `len(games)`가 3 이하인가 |
| "공포 게임은 싫어" | 추천된 게임의 `genres`·`themes`에 Horror가 없는가 |
| "RTX 3060인데" | 추천된 게임의 `hardware.check.status`가 `met`인가 |
| "무료 게임만" | `amount_krw`가 0인가 |

이 방식은 **추천의 품질(적절한 게임을 골랐는가)을 재지 않는다.** 계약 위반만 잡는다. 품질 쪽은
답변 문단에 대한 LLM 심판이 따로 본다.

기대값은 "추천이 비어 있지 않아야 한다"를 주장하지 않는다. IGDB·Steam 데이터에 따라 조건을
만족하는 후보가 실제로 없을 수 있고, 그때 빈 목록과 경고를 내는 것이 옳은 동작이다. 대신 빈
목록이면 경고가 이유를 설명하는지 검사한다.

## 계열

| 계열 | 문항 | 무엇을 보는가 |
| --- | --- | --- |
| budget | 20 | 명시 예산 상한을 추천 결과가 지키는가 |
| free | 10 | 무료 강제 조건에서 가격이 0원인가 |
| count | 15 | 추천 개수가 상한을 넘지 않는가 |
| exclude | 15 | 제외 장르가 `search_games`에 전달돼 추천에서 빠지는가 |
| hardware | 15 | 사양 판정이 `met`인 게임만 추천하는가 |
| tight | 5 | 아주 낮은 예산에서도 조건을 지키거나 경고하는가 |
| combined | 20 | 루트 README의 예상 질문 5개 + 복합 조건 15개 |

`exclude` 계열이 특히 에이전트를 본다. 제외 조건은 파서가 `excluded_genres`로 뽑아도
`search_games` 인자로 넘기는 것은 **에이전트(LLM)의 판단**이므로 빠뜨릴 수 있다.

## 채점

[score.py](score.py)가 세 축을 따로 낸다. 셋 다 통과해야 문항이 통과한다.

1. **constraints** — 필수 조건 준수. 코드로만 본다.
   - 공통: 가격·사양 판정이 `met`이나 `skipped`가 아닌 게임은 추천에 들어갈 수 없다
     (루트 README의 "실패나 누락은 필수 조건 통과로 처리하지 않는다"). 중복 `igdb_id` 없음,
     `recommendation_count` 이하, 빈 목록이면 경고가 있음.
   - 문항별: 위 표의 가격·개수·제외·사양 검사.
2. **trajectory** — 필요한 단계 실행. 진행 이벤트(`progress` 콜백)로 본다.
   공통 단계(질문 분해·에이전트 추론·게임 검색) 완료, 문항별 필수 단계 완료, 실패 단계 없음,
   `게임 검색`이 `가격`·`하드웨어`보다 먼저.
3. **answer_format** — 답변 문단의 형식. 한국어, 마크다운·표·링크 없음, 3~6문장,
   **추천한 게임이 모두 답변에 언급됨**. 마지막 항목이 실측에서 실제 결함을 잡았다(REPORT.md 참고).

[judge.py](judge.py)의 LLM 심판(`gpt-4o-mini`)이 코드로 볼 수 없는 두 가지를 1~5로 채점한다.
Tool 결과를 근거로 함께 넘긴다.

- **grounded** — 답변의 사실 주장이 Tool 결과로 뒷받침되는가. 근거에 없는 가격·평점·출시일을
  지어냈는지 본다.
- **linked** — 게임마다 사용자 조건과 연결된 이유를 썼는가.

심판도 틀리고 점수는 프롬프트에 의존한다. **자동 정확도에 섞지 않고 따로 보고한다.**
심판에 정답 라벨은 주지 않는다(애초에 없다).

**오류로 끝난 문항은 정확도 분모에서 뺀다.** 네트워크·레이트리밋 실패는 에이전트 품질이 아니라
실행 환경 문제이므로 `errors`로 따로 센다(`evals/price_hardware`와 같은 관례). 자동 재시도는
넣지 않았다.

## 실행

저장소 루트에서 실행한다. `.env`의 키를 읽는다.

```bash
.venv/bin/python -m evals.agent_e2e.run_eval --limit 5     # 먼저 작게 확인한다
.venv/bin/python -m evals.agent_e2e.run_eval               # 100문항, 약 $0.7
.venv/bin/python -m evals.agent_e2e.run_eval --no-judge    # LLM 심판 생략
.venv/bin/python -m evals.agent_e2e.run_eval --concurrency 2
```

동시성 기본값은 4다. 한 질문이 IGDB·Steam·CheapShark·환율·OpenAI를 여러 번 부르므로 동시성을
올리면 외부 API와 로컬 DNS에 부하가 몰린다. **실측에서 동시성 4로 돌렸을 때 100건 중 50건이
연결 오류로 끝났고, 2로 낮춰 다시 돌렸다.** 오류가 많으면 낮춰서 다시 돌린다.

LangSmith에는 `agent-e2e` 데이터셋으로 올라간다. 파서 평가와 달리 `aevaluate` 실험을 쓰지
않는다. 에이전트 실행은 `progress` 콜백으로 단계 기록을 받아야 하고, 그 기록이 궤적 채점의
입력이기 때문이다. 실행 자체의 트레이스는 `LANGSMITH_TRACING`으로 `LANGSMITH_PROJECT`에 남는다.

기록은 `runs/<UTC timestamp>/`에 남고 기존 디렉터리는 덮어쓰지 않는다. `metadata.json`에
모델·시각·데이터·에이전트 프롬프트 SHA-256, `results.jsonl`에 건별 결과·단계 타임라인·답변·
심판 점수, `summary.json`에 집계가 들어간다. 키는 기록하지 않는다.

```bash
.venv/bin/python evals/agent_e2e/build_dataset.py   # 데이터 재생성
.venv/bin/python -m pytest -q evals/agent_e2e/test_e2e_score.py
.venv/bin/python -m ruff check .
```

## 읽을 때 주의

- **결과는 실행 날짜와 함께 읽는다.** IGDB·Steam 데이터가 바뀌면 같은 질문에 다른 게임이 나온다.
  추천 목록이 실행마다 다른 것은 정상이다.
- 한 번의 측정이다. 에이전트의 Tool 선택은 LLM이 하므로 같은 질문에도 호출 순서·횟수가 달라진다.
  회귀 비교는 축별 통과 수와 위반 유형으로 하고, 추천 목록을 직접 비교하지 않는다.
- `constraints`가 통과해도 좋은 추천이라는 뜻은 아니다. 조건을 어기지 않았다는 뜻이다.
- 지연은 네트워크·모델 상태에 따라 흔들린다. 동시성 설정이 다르면 비교하지 않는다.
- 모델 alias의 서버측 버전을 고정하지 않았다.
