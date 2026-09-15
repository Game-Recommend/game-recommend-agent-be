# 실행·검증 명령을 한곳에 모은다. 인자 전달: make test-igdb ARGS="-q"
# .venv가 있으면 그 인터프리터를, 없으면 PATH의 python3를 쓴다.

PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: run lint test test-query-processing test-igdb test-price-hardware test-final-answer
.PHONY: test-reviews test-media test-integration test-llm

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

test-final-answer:
	$(PY) -m pytest tests/price_hardware/final_answer $(ARGS)

test-reviews:
	$(PY) -m pytest tests/reviews $(ARGS)

test-media:
	$(PY) -m pytest tests/media $(ARGS)

test-integration:
	$(PY) -m pytest tests/integration $(ARGS)
