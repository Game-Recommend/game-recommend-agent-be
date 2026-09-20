"""평가 실행기의 채점 오류·정답 유출을 막는 오프라인 검사."""

import asyncio
import json
from pathlib import Path

from app.schemas.hardware import HardwareAssessment
from evals.price_hardware.run_eval import evaluate, summarize

DATA = json.loads(Path(__file__).with_name("dataset.json").read_text())
BY_ID = {case["id"]: case for case in DATA}
# 판정기를 실제로 타면서 정답이 unknown인 문항. v2에서 사용자 부품이 불명인 문항(H08 등)은
# LLM 앞에서 skipped로 빠지므로 "판정이 없을 때"를 검사할 수 없다.
UNKNOWN_VIA_LLM = BY_ID["H13"]


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
    result = asyncio.run(evaluate(UNKNOWN_VIA_LLM, 1, StubJudge()))
    assert result["rows"][0]["actual"] == "unknown"
    assert not result["passed"]
    assert not result["rows"][0]["status_match"]


def test_api_error_is_not_correct_unknown_and_excluded_from_accuracy():
    result = asyncio.run(evaluate(UNKNOWN_VIA_LLM, 1, StubJudge(error=True)))
    assert not result["passed"]
    summary = summarize([result])["llm"]
    assert summary["api_errors"] == 1
    assert summary["valid_verdicts"] == 0


def test_expected_label_not_sent_and_fixture_preserves_minimum():
    judge = StubJudge("met")
    case = BY_ID["H01"]
    result = asyncio.run(evaluate(case, 1, judge))
    assert result["passed"]
    request = judge.requests[0].model_dump()
    # 필드를 정확히 비교한다. JudgeRequest에 필드가 늘면 여기서 걸려
    # 정답이 새지 않는지 다시 보게 된다.
    assert set(request) == {"igdb_id", "name", "requirement", "components"}
    assert request["requirement"]["gpu"] == case["games"][0]["minimum"]["gpu"]
    assert "expected" not in request and "expected" not in str(request)


def test_repeats_and_provisional_results_are_separate():
    first = asyncio.run(evaluate(BY_ID["H25"], 1, StubJudge("met")))
    second = asyncio.run(evaluate(BY_ID["H25"], 2, StubJudge("unmet")))
    summary = summarize([first, second])
    assert summary["llm"]["valid_verdicts"] == 2
    assert summary["llm_without_provisional"]["case_runs"] == 0
    assert summary["inconsistent_cases"] == ["H25"]
