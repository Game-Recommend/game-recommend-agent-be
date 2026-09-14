from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """실행 설정. `.env`에서 읽고, 키 목록의 원본은 `.env.example`이다."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # IGDB는 Twitch 개발자 앱의 client credentials로 앱 토큰을 받아 쓴다
    igdb_client_id: str = ""
    igdb_client_secret: str = ""
    # GPU·CPU 사양 판정(app/clients/hardware_judge.py)에 쓴다
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
