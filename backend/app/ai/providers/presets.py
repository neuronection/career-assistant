"""Provider preset catalog: named endpoints
the settings UI offers before "Custom". Career's model factory speaks the
OpenAI wire (``openai`` / ``openai_compatible``) plus native Gemini
(``google`` — ``chat_models.py``), so every preset maps onto those types.
Pure metadata — no secrets; the ``local`` flag only defaults the settings
form's hosting toggle."""

from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "openai": {
        "name": "OpenAI",
        "type": "openai",
        "base_url": "https://api.openai.com/v1",
        "local": False,
    },
    "gemini": {
        "name": "Google Gemini",
        "type": "google",
        "base_url": "https://generativelanguage.googleapis.com",
        "local": False,
    },
    "openrouter": {
        "name": "OpenRouter",
        "type": "openai_compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "local": False,
    },
    "groq": {
        "name": "Groq",
        "type": "openai_compatible",
        "base_url": "https://api.groq.com/openai/v1",
        "local": False,
    },
    "mistral": {
        "name": "Mistral",
        "type": "openai_compatible",
        "base_url": "https://api.mistral.ai/v1",
        "local": False,
    },
    "deepseek": {
        "name": "DeepSeek",
        "type": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "local": False,
    },
    "ollama": {
        "name": "Ollama (local)",
        "type": "openai_compatible",
        "base_url": "http://localhost:11434/v1",
        "local": True,
    },
    "llama_cpp": {
        "name": "llama.cpp (local)",
        "type": "openai_compatible",
        "base_url": "http://localhost:8080/v1",
        "local": True,
    },
    "lm_studio": {
        "name": "LM Studio (local)",
        "type": "openai_compatible",
        "base_url": "http://localhost:1234/v1",
        "local": True,
    },
}

PRESET_ORDER: tuple[str, ...] = (
    "openai",
    "gemini",
    "openrouter",
    "groq",
    "mistral",
    "deepseek",
    "ollama",
    "llama_cpp",
    "lm_studio",
)
