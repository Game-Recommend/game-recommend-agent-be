# 검색 후보 풀 평가

IGDB 검색(`app/clients/igdb.py`)이 문항별로 **어떤 후보를 내는지**만 보는 평가다. LLM을 부르지 않고,
가격·사양 판정과 에이전트도 돌리지 않는다. 최초 실측은 [REPORT.md](REPORT.md), 원시 기록은
[runs/](runs)에 있다.

엔드투엔드 평가(`evals/agent_e2e/`)는 추천이 조건을 지켰는지는 보지만 **무엇이 후보로 올라왔는지**는
보지 않는다. 후보 풀은 고정 파이프라인과 에이전트가 공유하고 추천의 질을 가장 크게 좌우하는데, 어느
평가도 재고 있지 않았다.

**실제 IGDB와 Steam 스토어를 부른다.** Steam 상세 API는 IP당 5분에 약 200회 제한이 있어 문항별 상위
후보만 1.6초 간격으로 조회한다. 100문항에 3~5분이 걸린다. LLM 비용은 없다. CI에서는 돌리지 않는다.

## 입력

[dataset.json](dataset.json)은 엔드투엔드 실행(100문항)과 취향 적합도 평가 실행(40문항)에서 **파서가
실제로 낸 조건**을 문항별로 고정한 것이다. 엔드투엔드 문항은 분류가 없거나 하나인 것이 대부분이라,
분류가 여럿이거나 파서가 분류를 지어내는 경우는 취향 적합도 평가의 기록에서 가져왔다(2026-09-20. 그 전의
`runs/before`·`runs/after`는 100문항이다). 질문을 다시 분해하지 않으므로 같은 입력으로 검색만 비교할 수 있다. 파서가 내는 어긋난 값
(`genres=["Cooperative"]`, `platforms=["노트북"]`, 제외할 장르를 `genres`에 넣은 경우)도 그대로 들어 있다.
검색이 그런 값을 어떻게 다루는지가 평가 대상이기 때문이다.

```bash
.venv/bin/python evals/search_pool/build_dataset.py \
    evals/agent_e2e/runs/<오류 없는 실행> evals/relevance/runs/<오류 없는 실행>
```

## 지표

| 지표 | 무엇을 보는가 |
| --- | --- |
| `zero_candidates` | 후보가 0개인 문항. 조건 매핑이 어긋나면 늘어난다 |
| `release_year_median` | 후보의 출시 연도 중앙값 |
| `most_common_head5` | 같은 게임이 몇 문항의 앞쪽 후보 5개에 드는가. 질문과 무관하게 같은 게임이 나오는 정도 |
| `distinct_games`, `distinct_games_head5` | 100문항에 걸쳐 나온 서로 다른 게임 수 |
| `on_steam` | Steam 앱 id가 연결된 후보 비율. 없으면 가격·사양이 비Steam 폴백으로 간다 |
| `steam_top10.kr_available` | 문항별 상위 10개 중 한국 스토어에서 조회되는 비율 |
| `steam_top10.has_requirements` | 최소 사양을 읽을 수 있는 비율. 낮으면 사양 판정이 `unknown`이 된다 |
| `steam_top10.price_le_10000` · `price_le_30000` · `free` | 예산 질문에서 살아남을 후보의 비율 |

Steam 쪽 비율의 분모는 **상세 조회에 성공한 Steam 후보**다. 상위 10개만 보는 것은 호출 제한 때문이고,
실제 서비스는 후보 30개를 모두 조회한다.

## 실행

저장소 루트에서 실행한다. `.env`의 IGDB 키를 읽는다.

```bash
.venv/bin/python -m evals.search_pool.run_eval --label <이름>      # runs/<이름>/에 기록
.venv/bin/python -m evals.search_pool.run_eval --label smoke --limit 5 --no-steam
.venv/bin/python -m pytest -q evals/search_pool/test_search_pool.py
```

`runs/<이름>/`에 `metadata.json`, 문항별 후보(`results.jsonl`), Steam 상세(`steam.json`),
집계(`summary.json`)가 남는다. 기존 디렉터리는 덮어쓰지 않는다.

## 읽을 때 주의

- IGDB의 평가 수와 Steam 가격은 날마다 바뀐다. 결과는 실행 날짜와 함께 읽는다.
- **추천의 질을 재지 않는다.** 후보가 질문에 어울리는지는 보지 않고, 후보 풀의 성질(연도·다양성·구매
  가능성)만 본다.
- 가격 지표는 그날의 할인에 흔들린다. 추세로 읽는다.
