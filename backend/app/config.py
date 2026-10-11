from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./projecta1.db"
    cors_origins: str = "http://localhost:3000"
    cookie_secure: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
