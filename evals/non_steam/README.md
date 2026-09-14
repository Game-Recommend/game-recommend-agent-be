# 비Steam 폴백 평가

`steam_app_id`가 없는 후보만 타는 폴백 경로의 실측 평가셋이다. 문항은 [questions.md](questions.md),
실행 데이터는 [dataset.json](dataset.json), 최초 실측 결과는 [REPORT.md](REPORT.md)에 있다.

평가 대상은 `PcGamingWikiClient`(요구 사양), `CheapSharkClient` + `ExchangeRateClient` + 무료 게임 표(가격),
`hardware_assessor.assess_requirements`(Steam·PCGamingWiki 공통 판정)다. 라우팅(`routing.py`)은 단위 테스트로
검증하므로 여기서는 부르지 않는다. 질문 파서, IGDB 검색, Steam 조회, 리뷰, 최종 답변은 포함하지 않는다.

기존 `evals/price_hardware/`와 달리 **실제 외부 API를 호출하는 스모크 성격**이다. PCGamingWiki·CheapShark
데이터는 시간이 지나면 바뀌므로 결과는 실행 날짜와 함께 읽어야 하고, CI에서는 돌리지 않는다.

- W01–W20: PCGamingWiki 매칭 여부, 최소 사양 유무, 파싱된 항목(os/cpu/gpu/ram_gb) 수. 기대값이 있는 6개만 채점한다.
- P01–P15: 무료 표 적중, CheapShark 정확 일치 후 원화 변환 범위, 정확 일치 실패 시 생략. `unavailable`은 0건이어야 한다.
- C01–C05: 같은 사양을 Steam HTML·PCGamingWiki 템플릿으로 넣었을 때 파싱 항목과 판정 상태가 같은지. C03·C04만 LLM.

가격 원화 범위는 정답 가격이 아니라 상식선의 경계(환율 오류·단위 오류 검출용)다.
사양 커버리지는 통과/실패보다 "폴백이 실제로 얼마나 사양을 채워 주는지"를 보는 수치다.
RAWG를 썼던 v2 결과와 비교하려고 문항 20개는 그대로 두었다.

## 실행

저장소 루트에서 실행한다. 외부 API 키는 필요 없고, `.env`의 `OPENAI_API_KEY`가 있으면 C03·C04도 실행한다.
실제 LLM 호출은 2회(사례당 후보 2개를 한 번에 판정)다. 자동 재시도는 꺼두었다.

```bash
.venv/bin/python -m evals.non_steam.run_eval            # 기본 출력: runs/<UTC timestamp>/
.venv/bin/python -m evals.non_steam.run_eval --no-llm   # LLM 사례 생략
```

`metadata.json`에 모델, 실행 시각, 데이터·프롬프트 SHA-256을 기록한다. `results.jsonl`은 건별 결과,
`summary.json`은 축별 집계다. 기존 결과 디렉터리는 덮어쓰지 않는다. 키와 인증 헤더는 기록하지 않는다.

정답은 모델 입력에 전달하지 않는다. 별도 LLM 채점기도 쓰지 않는다. 상태와 금액 범위를 코드로 비교한다.

```bash
# 데이터 재생성: 라벨을 바꾸면 기존 baseline의 해시와 달라지므로 새 디렉터리로 다시 실행한다.
.venv/bin/python evals/non_steam/build_dataset.py
# API를 호출하지 않는 채점기 검사 + 기존 전체 테스트
.venv/bin/python -m pytest -q tests evals/non_steam/test_non_steam_eval.py
make lint
```
