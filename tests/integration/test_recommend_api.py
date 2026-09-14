import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_recommender
from app.config import Settings, get_settings
from app.main import app

API_KEY = "test-key"
HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture(autouse=True)
def configured_api_key(monkeypatch):
    # 로컬 .env와 무관하게 키를 고정한다
    settings = Settings(api_key=API_KEY, _env_file=None)
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)


@pytest.fixture
def client(recommender, monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, get_recommender, lambda: recommender)
    with TestClient(app, headers=HEADERS) as client:
        yield client


def test_missing_or_wrong_api_key_is_rejected(recommender, monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, get_recommender, lambda: recommender)
    with TestClient(app) as client:
        assert client.post("/recommend", json={"question": "게임 추천"}).status_code == 401
        response = client.post(
            "/recommend", json={"question": "게임 추천"}, headers={"X-API-Key": "wrong"}
        )
        assert response.status_code == 401
        assert client.get("/health").status_code == 200  # 생존 확인은 키 없이 열려 있다


def test_unset_api_key_closes_recommend(recommender, monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, get_recommender, lambda: recommender)
    monkeypatch.setitem(
        app.dependency_overrides, get_settings, lambda: Settings(api_key="", _env_file=None)
    )
    with TestClient(app, headers=HEADERS) as client:
        response = client.post("/recommend", json={"question": "게임 추천"})
    assert response.status_code == 503
    assert "API_KEY" in response.json()["detail"]


def test_recommend_returns_structured_evidence(client):
    response = client.post("/recommend", json={"question": "게임 추천"})
    assert response.status_code == 200
    assert response.json()["games"][0]["game"]["igdb_id"] == 3
    assert response.json()["answer"] == "테스트 답변"


@pytest.mark.parametrize("question", ["", "   ", "x" * 5001])
def test_invalid_question_is_rejected(client, question):
    assert client.post("/recommend", json={"question": question}).status_code == 422


def test_unconfigured_service_returns_503():
    with TestClient(app, headers=HEADERS) as client:
        response = client.post("/recommend", json={"question": "게임 추천"})
    assert response.status_code == 503


def test_pipeline_can_be_injected_through_app_state(recommender, monkeypatch):
    monkeypatch.setattr(app.state, "recommender", recommender, raising=False)
    with TestClient(app, headers=HEADERS) as client:
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
