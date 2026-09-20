# 실행·검증 명령을 한곳에 모은다. 인자 전달: make test-igdb ARGS="-q"
# .venv가 있으면 그 인터프리터를, 없으면 PATH의 python3를 쓴다.

PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: run lint test test-query-processing test-igdb test-price-hardware
.PHONY: test-reviews test-media test-integration test-llm test-agent test-evals graph

run:
	$(PY) -m uvicorn app.main:app --reload

lint:
	$(PY) -m ruff check .

test:
	$(PY) -m pytest $(ARGS)

test-query-processing:
	$(PY) -m pytest tests/query_processing $(ARGS)

# 기존 명령 호환: 질문 가공만 검증한다.
test-llm: test-query-processing

test-igdb:
	$(PY) -m pytest tests/igdb $(ARGS)

test-price-hardware:
	$(PY) -m pytest tests/price_hardware $(ARGS)

test-reviews:
	$(PY) -m pytest tests/reviews $(ARGS)

test-media:
	$(PY) -m pytest tests/media $(ARGS)

test-integration:
	$(PY) -m pytest tests/integration $(ARGS)

# 에이전트: 후보 저장소·Tool 어댑터·루프(대본 모델로 OpenAI 없이 검증)
test-agent:
	$(PY) -m pytest tests/agent $(ARGS)

# 평가 채점기·실행기의 오프라인 검사 (실제 API를 부르지 않는다)
test-evals:
	$(PY) -m pytest evals $(ARGS)

# 발표·문서용 에이전트 그래프(Mermaid)
graph:
	$(PY) -m app.agent.runner
