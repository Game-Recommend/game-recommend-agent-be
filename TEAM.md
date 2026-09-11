# 역할별 개발 가이드

경로는 저장소 루트 기준입니다. 각 담당자는 자신의 도구·클라이언트·계약·테스트를 수정합니다.
실제 API·LLM 구현체는 아직 없으며, Protocol은 구현해야 할 비동기 입출력 계약입니다.

## 담당 파일

| 담당 | 구현·연동 영역 | 입력·출력 계약 | 테스트·대역 |
| --- | --- | --- | --- |
| 질문 가공 | `app/pipeline/query_processing/`의 parser·LLM 구현·프롬프트 | `app/pipeline/query_processing/conditions.py`, `app/pipeline/query_processing/parser.py` | `tests/query_processing/` |
| IGDB 필터링 | `app/clients/igdb.py`, `app/tools/game_search.py` | `app/clients/contracts/catalog.py`, `app/schemas/game.py` | `tests/igdb/` |
| 가격·하드웨어·최종 답변 | `app/clients/steam_store.py`, `app/clients/cheapshark.py`, `app/clients/rawg.py`; `app/tools/price.py`, `app/tools/hardware.py`; `app/pipeline/final_answer/`의 answerer·LLM 구현·프롬프트 | `app/clients/contracts/price.py`, `app/clients/contracts/hardware.py`; `app/schemas/price.py`, `app/schemas/hardware.py`; `app/pipeline/final_answer/answerer.py` | `tests/price_hardware/`, `tests/price_hardware/final_answer/` |
| 리뷰 요약 | `app/clients/steam_reviews.py`, `app/tools/review_summary.py`; 별도 요약 API를 쓰면 리뷰 담당자가 전용 클라이언트 추가 | `app/clients/contracts/reviews.py`, `app/schemas/review.py` | `tests/reviews/` |

Steam 상세 조회는 가격·하드웨어 담당, Steam 리뷰 조회는 리뷰 담당입니다.
양쪽 모두 IGDB 담당자가 제공한 `GameCandidate.steam_app_id`를 사용합니다.
식별자가 없을 때 게임명으로 임의 연결하지 말고 조회 불가로 처리합니다.

## 연결 계약

| 역할 | 함수 | 결과 |
| --- | --- | --- |
| 질문 분해 | `parse(question)` | `GameConditions` |
| IGDB | `search(conditions)` | `list[GameCandidate]` |
| 가격 | `fetch_prices(games)` | `list[PriceQuote]` |
| 하드웨어 | `assess(games, hardware)` | `list[HardwareAssessment]` |
| 리뷰 | `summarize(games)` | `list[ReviewSummary]` |
| 최종 답변 | `generate(question, evidence)` | `str` |

모든 함수는 `async def`입니다. 각 역할의 모듈에서 모델과 Protocol을 직접 import합니다.
계약을 한 파일에 다시 모으거나 Protocol을 실제 구현체로 대체하지 않습니다.
실제 구현 클래스는 계약을 만족하도록 별도로 작성합니다.

가격·하드웨어·최종 답변 담당자는 가격 조회, 사양 판정, 최종 답변을 각각 독립된
비동기 기능으로 구현합니다. 가격·사양의 병렬 실행과 결과 병합은
`app/pipeline/orchestrator.py`에서 처리하고, 최종 답변은 리뷰 요약 이후에 호출합니다.
같은 담당자가 구현해도 가격·사양 API 내부에서 최종 답변을 생성하지 않습니다.

질문 가공의 `QueryParser`와 최종 답변의 `Answerer`는 별도 객체로 주입합니다.
질문 분해 프롬프트는 `app/pipeline/query_processing/`, 답변 생성 프롬프트는
`app/pipeline/final_answer/`에서 각각 관리합니다. 구현체를 한 LLM 클래스에 합치지 않습니다.
리뷰 담당자는 전달받은 후보만 요약하며, 후보 선택·예산 판정을 반복하지 않습니다.

## 공통 영역

아래 파일은 통합 담당자가 관리하는 공통 영역입니다. 통합 담당자는 팀 내에서 정합니다.

- `app/pipeline/orchestrator.py`: 단계 연결·병렬 호출·후보 선택·실패 처리
- `app/schemas/common.py`: 조건 판정 상태
- `app/schemas/recommendation.py`: 최종 답변 근거와 HTTP 요청·응답
- `app/api/`, `app/main.py`: 엔드포인트와 구현체 연결
- `app/config.py`, `.env.example`, `pyproject.toml`: 설정과 의존성
- `tests/integration/`: 통합 시나리오·API·공통 조립 fixture

역할별 파일이어도 모델 필드·함수 시그니처를 바꾸면 소비자에게 영향을 줍니다.
특히 질문 조건은 질문 가공·IGDB·가격/하드웨어 담당자가, 게임 후보는 IGDB·후속 도구·최종 답변
담당자가 함께 맞춥니다.

## 역할별 테스트 실행

아래 명령은 저장소 루트에서 실행합니다.

```bash
make test-query-processing ARGS="-q"
make test-igdb ARGS="-q"
make test-price-hardware ARGS="-q"   # 가격·사양·최종 답변 모두
make test-final-answer ARGS="-q"     # 최종 답변만
make test-reviews ARGS="-q"
make test-integration ARGS="-q"
make test ARGS="-q"
make lint
```

각 역할의 `fakes.py`는 해당 담당자가 관리하는 테스트 전용 연동 대역입니다.
단위 테스트는 같은 역할의 대역만 사용합니다. 통합 테스트는 역할별 대역을
`tests/integration/conftest.py`에서 조립합니다. 모든 역할을 구현하는 공통 대역은 없습니다.
질문 가공은 `tests/query_processing/fakes.py`의 `FakeQueryParser`, 최종 답변은
`tests/price_hardware/final_answer/fakes.py`의 `FakeAnswerer`를 사용합니다.
최종 답변 담당자는 `tests/price_hardware/final_answer/test_boundary.py`에서 다른 팀원의 대역을 import하지 않고
질문·추천 근거 전달, 후보 없음, 답변 실패를 검증할 수 있습니다.

현재 역할별 테스트는 조건 모델과 도구의 경계 동작을 검증합니다. 실제 API 호출이나
LLM 출력 품질을 검증하지 않습니다. 연동 구현 시 자신의 디렉터리에 응답 변환·오류 처리
테스트를 추가하고, 병합 전 전체 테스트로 다른 역할과의 연결을 확인합니다.
