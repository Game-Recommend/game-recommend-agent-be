# 예상 질문 전후 비교

루트 [README](../../README.md)의 `## 예상 질문` 5개를 **고정 파이프라인(원본 저장소)과 에이전트(이 저장소)로
각각 실행해** Tool 호출 순서·횟수·지연·추천 결과를 남기는 평가다. 전환의 효과와 대가를 발표에서 설명하는
근거로 쓴다. 최초 실측은 [REPORT.md](REPORT.md), 원시 기록은 [runs/](runs)에 있다.

`evals/price_hardware/`와 달리 **실제 외부 API와 LLM을 부르는 스모크 성격**이다. 질문 하나에 20~40초와
OpenAI 비용이 들고, IGDB·Steam 응답이 바뀌면 후보도 바뀌므로 CI에서는 돌리지 않는다.

## 구성

| 파일 | 역할 |
| --- | --- |
| [bench.py](bench.py) | 질문 5개를 실행해 진행 이벤트(단계·시각·detail)와 추천 결과를 JSON으로 남긴다 |
| [report.py](report.py) | 두 기록을 마크다운(요약 표, 질문별 상세와 타임라인)으로 바꾼다 |
| `runs/<날짜>/{agent,baseline}.json` | 실행 원시 기록 |

질문은 코드에 적지 않고 루트 README의 `## 예상 질문` 불릿에서 읽는다. 질문이 바뀌면 README만 고친다.

## 실행

**대상 저장소의 venv로, 그 저장소 루트를 현재 디렉터리로** 실행한다. `.env`를 현재 디렉터리에서 읽고,
`app` 패키지는 각 venv에 editable로 설치된 것을 쓴다. 두 저장소 모두 `OPENAI_API_KEY`가 살아 있어야 한다.

```bash
# 에이전트 (이 저장소)
.venv/bin/python evals/agent_questions/bench.py --label agent

# 고정 파이프라인 (원본 저장소). 질문은 이 저장소 README에서 읽는다
cd ../game-recommend-be && .venv/bin/python \
  ../game-recommend-agent-be/evals/agent_questions/bench.py --label baseline
```

두 기록이 모이면 마크다운을 만든다. `--table`은 루트 README에 붙일 요약 표만, `--details`는 질문별
상세만 낸다. 관찰과 해석은 사람이 REPORT.md에 덧붙이므로 스크립트가 파일을 덮어쓰지 않는다.

```bash
RUNS=evals/agent_questions/runs/2026-09-17
.venv/bin/python evals/agent_questions/report.py $RUNS/agent.json $RUNS/baseline.json
```

## 읽을 때 주의

- 한 번의 측정이다. 지연은 네트워크·모델 상태에 따라 흔들리므로 추세로 읽는다.
- 원본과 에이전트의 추천 목록이 다른 것은 정상이다. 검색 인자를 에이전트는 LLM이 정하고, 원본은
  질문 분해 결과를 그대로 넘긴다.
- 에이전트 타임라인에서 `에이전트 추론`이 완료된 뒤에 나오는 Tool 단계는 러너 안전망이 부른 것이다.
