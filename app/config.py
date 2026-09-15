from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """실행 설정. `.env`에서 읽고, 키 목록의 원본은 `.env.example`이다."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # /recommend 호출에 필요한 공유 비밀. 프론트 서버 환경 변수에만 두고 브라우저에 내리지 않는다.
    # 비어 있으면 /recommend는 503을 돌려준다(실수로 열린 채 배포되지 않게).
    api_key: str = ""
    # IGDB는 Twitch 개발자 앱의 client credentials로 앱 토큰을 받아 쓴다
    igdb_client_id: str = ""
    igdb_client_secret: str = ""
    # SteamGridDB 히어로·로고 조회(app/clients/steamgriddb.py). 프로필 설정에서 무료 발급
    steamgriddb_api_key: str = ""
    # GPU·CPU 사양 판정(app/clients/hardware_judge.py)에 쓴다
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
