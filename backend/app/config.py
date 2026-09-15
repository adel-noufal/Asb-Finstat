from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Optional SEC access: app name and real contact email; no API key required.
    sec_user_agent: str = ""

    # One model knob per AI call — override any of these in backend/.env
    model_company_search: str = "openai/gpt-4o-mini"       # AI call #1
    model_find_statements: str = "perplexity/sonar"        # AI call #2 (needs web search)
    model_language_check: str = "openai/gpt-4o-mini"       # AI call #3
    model_translate: str = "google/gemini-2.5-flash"       # AI call #4 (Adel)
    model_extract: str = "anthropic/claude-sonnet-4.5"     # AI call #5 (Sophie)

    download_dir: Path = Path("data/downloads")
    extraction_dir: Path = Path("data/extractions")
    extract_ocr_mode: Literal["auto", "off", "required"] = "auto"
    extract_use_llm: bool = True


settings = Settings()
