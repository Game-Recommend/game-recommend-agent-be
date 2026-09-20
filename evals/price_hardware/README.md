# 가격·하드웨어 평가

자연어 질문 50개와 정규화 입력·기대값을 고정한 합성 경계 평가셋이다.
질문 목록은 [questions.md](questions.md), 실행 데이터는 [dataset.json](dataset.json),
최초 실제 호출 결과는 [REPORT.md](REPORT.md)에 있다.

평가 대상은 기존 `SteamStoreClient` → `HardwareTool`/`PriceTool`과 `OpenAISpecJudge`다.
가격·요구 사양은 고정 Steam HTTP 응답으로 제공하고 GPU·CPU 판정만 실제 OpenAI에 요청한다.
질문 텍스트를 파싱하지 않으며 질문 파서, IGDB 검색, 리뷰, 최종 답변은 포함하지 않는다.
`--live-steam`은 별도로 실제 Steam 조회 3건을 수행한다. 이 조회는 고정 정답 점수에 섞지 않는다.

- H01–H30: 실제 LLM 판정. H30은 한 질문에 후보 3개이므로 30질문/32판정이다.
- H31–H40: RAM 규칙, 사용자/게임 사양 누락, ID 누락, 최소·권장 분리.
- P41–P50: 예산 경계, 무료, 미출시, 미판매, 외화, 번들 가격 누락.
- H25–H27은 독립 벤치마크 검증 전 잠정 성능 라벨, H28은 보수적 정책 제안이다.
  이 4개를 제외한 점수도 따로 보고한다. 나머지도 사람이 승인한 정답셋은 아니다.
- CPU/GPU를 일부만 제공하면 제공된 항목만 판정하는 현재 계약을 따른다.
  `met`이 PC 전체 실행 가능성이나 FPS를 보증하지 않는다. OS 비교는 현재 미지원이다.

모든 경우를 망라하지 않는다. 근접 성능의 교차 제조사 비교, 내장 GPU의 모델·전력·메모리 구성,
DirectX 기능 조건, 드라이버, macOS/Linux 호환성, 성능 목표, 긴 후보 목록, 모든 Steam 응답 변형은
추가 평가 대상이다. 네트워크 실패·판정기 실패는 기존 단위 테스트와 별도 장애 평가가 필요하다.

## 실행

저장소 루트에서 실행한다. 기존 `.env`의 `OPENAI_API_KEY`, `OPENAI_MODEL`을 읽는다.
실제 LLM 호출은 유료이며 기본 60회(30질문 × 2회) 호출한다. 자동 재시도는 꺼두었다.
인증/연결 확인용 첫 호출에 실패하면 나머지 LLM 실행은 중단한다.

```bash
.venv/bin/python -m evals.price_hardware.run_eval --repeats 2 --live-steam
```

기본 출력 경로는 `runs/<UTC timestamp>/`다. 기존 결과 디렉터리는 덮어쓰지 않는다.
`metadata.json`에 모델, 실행 시각, 데이터·프롬프트 SHA-256을 기록한다.
`results.jsonl`은 판정 상태·근거와 건별 결과, `summary.json`은 집계,
`steam_live.json`은 실제 Steam 정규화 조회 결과다. 키와 인증 헤더는 기록하지 않는다.
API 사용 토큰과 청구 비용은 현재 기록하지 않으며 모델 alias의 서버측 버전도 고정하지 않았다.

정답은 모델 입력에 전달하지 않는다. 별도 LLM 채점기도 사용하지 않는다.
정답 상태를 코드로 비교하고 오류 응답은 정확도 분모에서 제외해 별도 집계한다.
빈 응답이 도구에서 `unknown`으로 바뀌는 경우와 중복 ID 응답은 정답으로 인정하지 않는다.
근거 문장의 사실성/논리적 일관성은 자동 정확도에 포함하지 않고 보고서에서 별도 검토한다.

```bash
# 데이터 재생성: 평가 버전 변경 시 기존 baseline과 해시를 반드시 구분한다.
.venv/bin/python evals/price_hardware/build_dataset.py
# API를 호출하지 않는 평가 실행기 검사 + 기존 전체 테스트
LANGSMITH_TRACING=false .venv/bin/python -m pytest -q tests evals/price_hardware/test_eval.py
make lint
```

이 파일은 `make test`와 CI에도 포함된다(`testpaths = ["tests", "evals"]`). 2026-09-21까지는 빠져 있어
검사 3건이 깨진 채로 남아 있었다. v2의 라벨 변경(H08이 LLM 호출 전에 `skipped`로 빠진다)과
`JudgeRequest`에 추가된 `components` 필드를 반영하지 않은 것이었고, 지금은 고쳤다. 정답이 `unknown`이면서
판정기를 타는 문항은 `H13`이라 그쪽을 쓴다. 문항은 인덱스가 아니라 id로 집는다.

설계 참고: [OpenAI Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices).
경계 사례와 작업별 평가, 반복 평가를 적용했다. 본 평가셋의 하드웨어 성능 라벨을 보증하는 출처는 아니다.
