"""평가 실행기의 채점 오류·정답 유출을 막는 오프라인 검사."""

import asyncio
import json
from pathlib import Path

from app.schemas.hardware import HardwareAssessment
from evals.price_hardware.run_eval import evaluate, summarize

DATA = json.loads(Path(__file__).with_name("dataset.json").read_text())


class StubJudge:
    def __init__(self, status=None, error=False):
        self.status = status
        self.error = error
        self.requests = []

    async def judge(self, hardware, requests):
        self.requests.extend(requests)
        if self.error:
            raise RuntimeError("offline failure")
        if self.status is None:
            return []
        return [
            HardwareAssessment(igdb_id=r.igdb_id, status=self.status, reason="검사")
            for r in requests
        ]


def test_missing_llm_response_does_not_pass_unknown_gold():
    result = asyncio.run(evaluate(DATA[7], 1, StubJudge()))
    assert result["rows"][0]["actual"] == "unknown"
    assert not result["passed"]
    assert not result["rows"][0]["status_match"]


def test_api_error_is_not_correct_unknown_and_excluded_from_accuracy():
    result = asyncio.run(evaluate(DATA[7], 1, StubJudge(error=True)))
    assert not result["passed"]
    summary = summarize([result])["llm"]
    assert summary["api_errors"] == 1
    assert summary["valid_verdicts"] == 0


def test_expected_label_not_sent_and_fixture_preserves_minimum():
    judge = StubJudge("met")
    result = asyncio.run(evaluate(DATA[0], 1, judge))
    assert result["passed"]
    request = judge.requests[0].model_dump()
    assert set(request) == {"igdb_id", "name", "requirement"}
    assert request["requirement"]["gpu"] == DATA[0]["games"][0]["minimum"]["gpu"]
    assert "expected" not in request


def test_repeats_and_provisional_results_are_separate():
    first = asyncio.run(evaluate(DATA[24], 1, StubJudge("met")))
    second = asyncio.run(evaluate(DATA[24], 2, StubJudge("unmet")))
    summary = summarize([first, second])
    assert summary["llm"]["valid_verdicts"] == 2
    assert summary["llm_without_provisional"]["case_runs"] == 0
    assert summary["inconsistent_cases"] == ["H25"]
