"""`/recommend`의 SSE 응답. `Accept: text/event-stream`일 때만 진행 이벤트를 흘린다."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_recommender
from app.api.routes import encode_sse
from app.config import Settings, get_settings
from app.main import app
from app.schemas.recommendation import StageEvent

HEADERS = {"X-API-Key": "test-key", "Accept": "text/event-stream"}


@pytest.fixture
def client(recommender, monkeypatch):
    monkeypatch.setitem(
        app.dependency_overrides, get_settings, lambda: Settings(api_key="test-key", _env_file=None)
    )
    monkeypatch.setitem(app.dependency_overrides, get_recommender, lambda: recommender)
    with TestClient(app) as client:
        yield client


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for frame in text.strip().split("\n\n"):
        lines = [line for line in frame.splitlines() if not line.startswith(":")]
        if not lines:
            continue
        fields = dict(line.split(": ", 1) for line in lines)
        events.append((fields["event"], json.loads(fields["data"])))
    return events


def test_stream_emits_stages_then_result(client, services):
    with client.stream("POST", "/recommend", json={"question": "게임 추천"}, headers=HEADERS) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(r.read().decode())

    names = [event for event, _ in events]
    assert names[0] == "stage" and names[-1] == "result"
    stages = [(d["stage"], d["status"]) for e, d in events if e == "stage"]
    assert stages[:4] == [
        ("질문 분해", "started"),
        ("질문 분해", "completed"),
        ("게임 검색", "started"),
        ("게임 검색", "completed"),
    ]
    assert ("조건 판정", "completed") in stages
    assert ("최종 답변 생성", "completed") == stages[-1]
    details = {(d["stage"], d["status"]): d["detail"] for e, d in events if e == "stage"}
    assert details[("게임 검색", "completed")] == "후보 3개"
    assert details[("조건 판정", "completed")] == "통과 1개 중 1개 선택, 제외 2개"
    result = events[-1][1]["result"]
    assert result["games"][0]["game"]["igdb_id"] == 3
    assert result["answer"] == "테스트 답변"


def test_stream_reports_required_stage_failure_as_error_event(client, services, monkeypatch):
    async def fail(question):
        raise ConnectionError("secret-provider-message")

    monkeypatch.setattr(services.parser, "parse", fail)
    with client.stream("POST", "/recommend", json={"question": "게임 추천"}, headers=HEADERS) as r:
        assert r.status_code == 200  # 스트림은 이미 열렸으므로 오류는 이벤트로 전달한다
        text = r.read().decode()
    events = parse_sse(text)
    statuses = [(e, d.get("status")) for e, d in events]
    assert statuses[:2] == [("stage", "started"), ("stage", "failed")]
    assert events[-1][0] == "error"
    assert "질문 분해" in events[-1][1]["detail"]
    assert "secret-provider-message" not in text


def test_optional_stage_failure_is_a_stage_event_not_an_error(client, services, monkeypatch):
    async def fail(games):
        raise ConnectionError("down")

    monkeypatch.setattr(services.reviews, "summarize", fail)
    with client.stream("POST", "/recommend", json={"question": "게임 추천"}, headers=HEADERS) as r:
        events = parse_sse(r.read().decode())
    assert ("리뷰 요약", "failed") in [(d.get("stage"), d.get("status")) for _, d in events]
    assert events[-1][0] == "result"
    assert any("리뷰 요약 호출 실패" in w for w in events[-1][1]["result"]["warnings"])


def test_json_accept_still_returns_plain_json(client):
    headers = {**HEADERS, "Accept": "application/json"}
    response = client.post("/recommend", json={"question": "게임 추천"}, headers=headers)
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["answer"] == "테스트 답변"


def test_stream_requires_api_key(recommender, monkeypatch):
    monkeypatch.setitem(
        app.dependency_overrides, get_settings, lambda: Settings(api_key="test-key", _env_file=None)
    )
    monkeypatch.setitem(app.dependency_overrides, get_recommender, lambda: recommender)
    with TestClient(app) as client:
        response = client.post(
            "/recommend", json={"question": "게임 추천"}, headers={"Accept": "text/event-stream"}
        )
    assert response.status_code == 401


def test_encoder_sends_heartbeat_while_stage_is_slow():
    async def slow_events():
        await asyncio.sleep(0.05)
        yield StageEvent(stage="질문 분해", status="started")

    async def collect():
        return [frame async for frame in encode_sse(slow_events(), heartbeat_seconds=0.01)]

    frames = asyncio.run(collect())
    assert frames[0] == ": keep-alive\n\n"
    assert frames[-1].startswith("event: stage\ndata: ")
