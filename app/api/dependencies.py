import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.assembly import ensure_assembled, missing_settings
from app.config import Settings, get_settings
from app.pipeline.orchestrator import RecommendationOrchestrator


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """`X-API-Key` 헤더가 설정된 API_KEY와 같아야 한다. 프론트 서버만 이 키를 안다."""
    if not settings.api_key:
        raise HTTPException(status_code=503, detail="API_KEY가 설정되지 않았습니다.")
    if x_api_key is None or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="API 키가 없거나 올바르지 않습니다.")


async def get_recommender(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> RecommendationOrchestrator:
    """app.state.recommender를 주입한다. 없으면 설정으로 한 번 조립하고, 키가 없으면 503이다."""
    recommender = await ensure_assembled(request.app.state, settings)
    if recommender is None:
        missing = ", ".join(missing_settings(settings))
        raise HTTPException(
            status_code=503,
            detail=f"추천 서비스의 외부 연동이 설정되지 않았습니다. 누락된 환경 변수: {missing}",
        )
    return recommender
