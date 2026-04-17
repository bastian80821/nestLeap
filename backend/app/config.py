from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3-flash-preview"
    gemini_fallback_model: str = "gemini-2.5-flash"
    database_url: str = "sqlite:///./nestleap.db"
    admin_key: str = "changeme"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
