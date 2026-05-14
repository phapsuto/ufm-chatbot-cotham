"""app/config.py — Cấu hình tập trung, đọc từ .env"""
from functools import lru_cache
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    FPT_CLOUD_API_KEY: str = ""
    FPT_CLOUD_BASE_URL: str = "https://mkp-api.fptcloud.com/v1"
    FPT_CLOUD_DEFAULT_MODEL: str = "Qwen3-32B"
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 2048
    LLM_STREAM: bool = True
    CACHE_TTL_HTML: int = 900
    CACHE_TTL_PDF: int = 43200
    CACHE_MAX_SIZE: int = 100
    DEBUG_MODE: bool = False
    PORT: int = 8000
    ALLOWED_DOMAIN: str = "daotaosdh.ufm.edu.vn"
    # Tesseract OCR
    TESSDATA_PREFIX: str = ""
    TESSERACT_LANG: str = "vie+eng"
    OCR_DPI: int = 300
    OCR_MIN_TEXT_LENGTH: int = 100
    MAX_PDF_SIZE_MB: int = 25
    # CRM
    CRM_DASHBOARD_PASSWORD: str = "ufm_crm_2026"
    CRM_SESSION_SECRET: str = "ufm-crm-secret-key"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
