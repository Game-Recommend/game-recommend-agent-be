# 질문 파서 평가

자연어 질문 200개와 `GameConditions` 정답을 고정한 평가셋이다. 질문 목록은
[questions.md](questions.md), 실행 데이터는 [dataset.json](dataset.json), 최초 실측은
[REPORT.md](REPORT.md), 원시 기록은 [runs/](runs)에 있다.

평가 대상은 `LLMQueryParser`(`app/pipeline/query_processing/llm_parser.py`) 하나다.
질문을 `GameConditions`로 바꾸는 계약만 본다. IGDB 검색, 가격·사양 조회, 리뷰, 에이전트
루프, 최종 답변은 포함하지 않는다. 외부 API를 부르지 않으므로 결과가 시간에 따라 바뀌지
않고, 200문항 1회가 약 $0.05·2분이라 회귀 검사로 반복할 수 있다.

**정답의 근거는 `game-recommend-agent-be`의 `QUERY_PARSER_SYSTEM`이다.** 문항마다 어느 절의 어떤
규칙인지 `basis`에 적었다. 프롬프트를 고치면 어느 문항이 흔들릴지 `basis`로 찾는다. 프롬프트가
정하지 않은 것은 정답으로 삼지 않았다.

이 평가셋은 두 저장소에 같은 내용으로 있다(`evals/price_hardware`와 같은 관례). 원본
`game-recommend-be`에서 돌리면 **원본 파서를 에이전트 저장소의 계약으로 채점**하는 것이 되므로,
수치는 "원본에 버그가 몇 개"가 아니라 **"전환 과정에서 계약이 얼마나 지켜지게 됐는가"**로 읽는다.
두 저장소의 프롬프트에는 이 평가셋이 의존하는 규칙이 모두 있고 `GameConditions` 필드도
동일하므로(`recommendation_count` 기본값 5까지) 정답 자체는 양쪽에 유효하다. 다른 것은
`conditions.py`의 validator 유무다 — REPORT.md의 전후 비교 절을 보라.

## 계열

| 계열 | 문항 | 무엇을 보는가 |
| --- | --- | --- |
| price | 30 | `max_price_krw` 경계(이하·미만·이내·까지), 무료 강제와 무료 선호, 모호 표현 |
| time | 25 | 세션 길이(`max_session_minutes`)와 총 플레이타임(`max_playtime_hours`) 혼동 |
| players | 30 | 인원 계산(`친구 N명과` vs `친구 N명이서`), `connection`, `play_mode` |
| hardware | 30 | 사양 추출, VRAM을 시스템 RAM으로 오인, PC는 플랫폼이지 사양이 아님 |
| genres | 36 | 카테고리 매핑, 긍정·부정 의도 분리, 수식어가 카테고리를 막지 않음 |
| count | 15 | `recommendation_count`. 미지정은 5(프롬프트 6절·스키마 기본값 일치) |
| no_dup | 14 | 전용 필드가 있는 조건을 `preferences`에 중복하지 않음 |
| combined | 20 | 루트 README의 예상 질문 5개 + 복합 조건 15개 |

## 채점

`score.py`가 코드로만 비교한다. 정답은 모델 입력에 전달하지 않고 별도 LLM 채점기도 쓰지
않는다(`evals/price_hardware`와 같은 원칙).

- **부분 정답**: `gold`에 적은 필드만 채점한다. 적지 않은 필드는 보지 않는다. `gold`에 명시한
  `None`은 "null이어야 한다"는 주장이고, 키가 없으면 주장하지 않는다.
- **집합 비교**: `genres`·`excluded_genres`·`platforms`는 순서를 보지 않는다.
- **표기 차이 허용**: `hardware.cpu`·`gpu`·`os`는 공백·하이픈·대소문자를 무시하고 비교한다.
  `raw_text`는 어느 구간을 담을지 계약이 정하지 않아 채점하지 않는다.
- **preferences**: 자유 어휘라 정확 일치를 요구하지 않고 포함(`pref_has`)·불포함(`pref_lacks`)·
  비어 있지 않음(`pref_nonempty`)만 본다.
- **공통 불변식**: `gold`와 무관하게 전 문항에 적용한다 — `hardware.os`가 플랫폼 표현이 아님,
  가격 상한이 있으면 `preferences`에 가격 표현이 없음, `max_price_krw=0`과 무료 표현이
  공존하지 않음, 두 시간 필드가 같은 시각을 가리키지 않음, 빈 `hardware`는 `null`.

문항이 "통과"했다는 것은 **모든 반복이 통과**했다는 뜻이다. 반복 사이에 갈린 문항은 `flaky`로
따로 센다. 프롬프트를 고쳐 해결할 버그와 모델 흔들림을 섞지 않기 위한 구분이다.

## 실행

저장소 루트에서 실행한다. `.env`의 `OPENAI_API_KEY`와 `LANGSMITH_API_KEY`를 읽는다.

```bash
# 3회 반복. 200문항 x 3 = 600회 호출, 약 $0.15 / 4분
.venv/bin/python -m evals.parser_conditions.run_eval --repeats 3 --concurrency 8

# 1회. 약 $0.05 / 2분
.venv/bin/python -m evals.parser_conditions.run_eval

.venv/bin/python -m evals.parser_conditions.run_eval --limit 20    # 앞 20문항만
.venv/bin/python -m evals.parser_conditions.run_eval --no-langsmith  # 로컬 기록만
```

LangSmith에는 `parser-conditions` 데이터셋과 `parser-conditions-<해시>` 실험으로 올라간다.
문항이 늘거나 정답이 바뀌면 실행할 때 데이터셋을 맞춘다. 데이터셋에만 남은 문항은 과거 실험과의
비교가 끊기므로 자동으로 지우지 않고 이름만 알려 준다.

LangSmith에 올리지 않아도 `runs/<UTC timestamp>/`에 같은 기록을 남긴다. 기존 디렉터리는
덮어쓰지 않는다. `metadata.json`에 모델·시각·데이터·프롬프트 SHA-256과 실험 이름,
`results.jsonl`에 건별 결과와 실패 사유, `summary.json`에 집계가 들어간다. 키는 기록하지 않는다.

```bash
# 데이터 재생성. 정답을 바꾸면 기존 runs/의 dataset_sha256과 달라진다
.venv/bin/python evals/parser_conditions/build_dataset.py
.venv/bin/python -m pytest -q evals/parser_conditions/test_parser_score.py
.venv/bin/python -m ruff check .
```

## 읽을 때 주의

- 정확도는 **프롬프트 계약을 얼마나 지키는지**의 수치다. 계약 자체가 옳은지는 별개 문제이고,
  실제로 REPORT.md의 관찰 2·3은 계약이 정하지 않은 구간을 가리킨다.
- `preferences`의 자유 문장이 사람이 보기에 적절한지는 채점하지 않는다.
- 모든 경우를 망라하지 않는다. 한 질문에 여러 게임 이름이 나오는 경우, 조건이 서로 모순되는
  질문, 한국어가 아닌 질문, 프롬프트 주입 시도는 추가 평가 대상이다.
- 이 평가셋의 카테고리 이름은 프롬프트가 매핑 예시로 든 10개에 한정한다. IGDB의 실제 장르·테마
  목록을 보증하지 않는다.
