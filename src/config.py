"""Application configuration and Zero-Cost multi-provider LLM factory (ADR-0004)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProviderMode = Literal["heuristic", "groq", "gemini", "ollama", "openai"]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Getnet Multi-Agent Support System"
    app_version: str = "0.1.0"
    llm_provider: LLMProviderMode = "heuristic"

    # Optional provider credentials / endpoints
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # Data & storage paths
    data_dir: Path = Path("data")
    sqlite_db_path: Path = Path("data/support.db")
    knowledge_base_path: Path = Path("data/getnet_knowledge_base.md")
    getnet_scrape_url: str = "https://www.getnet.net/en"
    enable_live_web_scrape: bool = True

    def resolved_llm_provider(self) -> LLMProviderMode:
        """Return the effective LLM provider, falling back to heuristic if credentials are absent."""
        if self.llm_provider == "groq" and self.groq_api_key:
            return "groq"
        if self.llm_provider == "gemini" and self.gemini_api_key:
            return "gemini"
        if self.llm_provider == "openai" and self.openai_api_key:
            return "openai"
        if self.llm_provider == "ollama":
            return "ollama"
        return "heuristic"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


def generate_completion(
    system_prompt: str,
    user_prompt: str,
    fallback_text: str,
    timeout_seconds: float = 8.0,
) -> str:
    """Execute LLM completion via configured Zero-Cost provider port with deterministic fallback."""
    settings = get_settings()
    provider = settings.resolved_llm_provider()
    if provider == "heuristic":
        return fallback_text

    try:
        if provider == "groq" and settings.groq_api_key:
            response = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                json={
                    "model": settings.groq_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()

        if provider == "openai" and settings.openai_api_key:
            response = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()

        if provider == "gemini" and settings.gemini_api_key:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
            )
            response = httpx.post(
                url,
                json={
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"parts": [{"text": user_prompt}]}],
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            return (
                response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            )

        if provider == "ollama":
            response = httpx.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            return response.json()["message"]["content"].strip()
    except Exception:
        return fallback_text

    return fallback_text

