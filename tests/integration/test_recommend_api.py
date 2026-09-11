import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_recommender
from app.main import app


@pytest.fixture
def client(recommender, monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, get_recommender, lambda: recommender)
    with TestClient(app) as client:
        yield client


def test_recommend_returns_structured_evidence(client):
    response = client.post("/recommend", json={"question": "게임 추천"})
    assert response.status_code == 200
    assert response.json()["games"][0]["game"]["igdb_id"] == 3
    assert response.json()["answer"] == "테스트 답변"


@pytest.mark.parametrize("question", ["", "   ", "x" * 5001])
def test_invalid_question_is_rejected(client, question):
    assert client.post("/recommend", json={"question": question}).status_code == 422


def test_unconfigured_service_returns_503():
    with TestClient(app) as client:
        response = client.post("/recommend", json={"question": "게임 추천"})
    assert response.status_code == 503


def test_pipeline_can_be_injected_through_app_state(recommender, monkeypatch):
    monkeypatch.setattr(app.state, "recommender", recommender, raising=False)
    with TestClient(app) as client:
        response = client.post("/recommend", json={"question": "게임 추천"})
    assert response.status_code == 200
    assert response.json()["games"][0]["game"]["igdb_id"] == 3


@pytest.mark.parametrize("method", ["parse", "search", "generate"])
def test_required_stage_failure_returns_502(client, services, monkeypatch, method):
    async def fail(*args):
        raise ConnectionError("secret-provider-message")

    target = {"parse": services.parser, "search": services.catalog, "generate": services.answerer}[
        method
    ]
    monkeypatch.setattr(target, method, fail)
    response = client.post("/recommend", json={"question": "게임 추천"})
    assert response.status_code == 502
    assert "secret-provider-message" not in response.text
