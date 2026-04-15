"""
Multi-provider LLM abstraction.

Priority order (configurable via CARGO_LLM_PRIORITY):
  1. "groq"     — fast cloud inference, requires GROQ_API_KEY
  2. "ollama"   — local, free, no API key needed
  3. "openai"   — requires OPENAI_API_KEY
  4. "anthropic" — requires ANTHROPIC_API_KEY

Set CARGO_LLM_PRIORITY to change order, e.g. "ollama,groq,openai"
Set CARGO_LLM_ENABLED=0 to force deterministic mode (no LLM at all).

Each provider is tried in order; first one that responds wins.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

_cached_provider: Optional[str] = None
_cached_llm = None


def _try_groq():
    key = os.environ.get("GROQ_API_KEY", "")
    if not key or key == "your-key-here":
        return None
    model = os.environ.get("CARGO_GROQ_MODEL", "llama-3.3-70b-versatile")
    try:
        from langchain_groq import ChatGroq
        llm = ChatGroq(model=model, temperature=0.1, max_tokens=1024, api_key=key)
        logger.info("LLM provider: Groq (%s)", model)
        return llm
    except Exception as e:
        logger.warning("Groq init failed: %s", e)
        return None


def _try_ollama():
    model = os.environ.get("CARGO_OLLAMA_MODEL", "qwen2.5:7b")
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if r.status_code != 200:
            return None
    except Exception:
        return None
    from langchain_ollama import ChatOllama
    logger.info("LLM provider: Ollama (%s)", model)
    return ChatOllama(model=model, temperature=0.1, num_predict=1024)


def _try_openai():
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key or key == "your-key-here":
        return None
    model = os.environ.get("CARGO_OPENAI_MODEL", "gpt-4o-mini")
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=model, temperature=0.1, max_tokens=1024, api_key=key)
        logger.info("LLM provider: OpenAI (%s)", model)
        return llm
    except Exception as e:
        logger.warning("OpenAI init failed: %s", e)
        return None


def _try_anthropic():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or key == "your-key-here":
        return None
    model = os.environ.get("CARGO_ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
    try:
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model=model, temperature=0.1, max_tokens=1024, api_key=key)
        logger.info("LLM provider: Anthropic (%s)", model)
        return llm
    except Exception as e:
        logger.warning("Anthropic init failed: %s", e)
        return None


_PROVIDERS = {
    "groq": _try_groq,
    "ollama": _try_ollama,
    "openai": _try_openai,
    "anthropic": _try_anthropic,
}


def get_llm(force_refresh: bool = False):
    """
    Return the best available LLM, trying providers in priority order.
    Returns None if no provider is available (triggers deterministic fallback).
    """
    global _cached_provider, _cached_llm

    if os.environ.get("CARGO_LLM_ENABLED", "1") == "0":
        _cached_llm = None
        _cached_provider = None
        return None

    if _cached_llm is not None and not force_refresh:
        return _cached_llm

    priority = os.environ.get("CARGO_LLM_PRIORITY", "groq,ollama,openai,anthropic").split(",")

    for name in priority:
        name = name.strip().lower()
        factory = _PROVIDERS.get(name)
        if factory is None:
            logger.debug("Unknown LLM provider '%s' in priority list, skipping", name)
            continue
        llm = factory()
        if llm is not None:
            _cached_provider = name
            _cached_llm = llm
            return llm

    _cached_llm = None
    _cached_provider = None
    logger.info("No LLM provider available; falling back to deterministic")
    return None


def get_provider_name() -> str:
    """Return the active provider name, or 'deterministic'."""
    if _cached_provider:
        return _cached_provider
    if get_llm() is not None:
        return _cached_provider or "unknown"
    return "deterministic"


def get_model_name() -> str:
    """Return the active model name."""
    provider = get_provider_name()
    if provider == "groq":
        return os.environ.get("CARGO_GROQ_MODEL", "llama-3.3-70b-versatile")
    if provider == "ollama":
        return os.environ.get("CARGO_OLLAMA_MODEL", "qwen2.5:7b")
    if provider == "openai":
        return os.environ.get("CARGO_OPENAI_MODEL", "gpt-4o-mini")
    if provider == "anthropic":
        return os.environ.get("CARGO_ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
    return "none"
