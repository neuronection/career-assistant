"""Offline machine-translation pass for the frontend locale catalogs.

The product path for translations is the gateway `translate` task (audited);
this script is the maintainer's offline batch tool: it reads `en.json`, asks a
local Ollama model for each batch, validates placeholders, and writes the
locale file. Nothing leaves the machine.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCALES = ROOT / "frontend" / "src" / "locales"
OLLAMA = "http://127.0.0.1:11434/api/chat"
MODEL = "translategemma:4b-it-q4_K_M"
BATCH = 16
KEEP = [
    "Neuronection",
    "Career Assistant",
    "GitHub",
    "LinkedIn",
    "Google",
    "OpenAI",
    "OpenRouter",
    "Ollama",
    "LM Studio",
    "Slack",
    "Microsoft Teams",
    "Telegram",
    "ntfy",
    "Cursor",
    "ATS",
    "CV",
    "PDF",
    "DOCX",
    "JSON",
    "API",
    "MCP",
    "OCR",
    "CEFR",
    "URL",
    "SMTP",
    "RSS",
    "ORCID",
]
PLACEHOLDER = re.compile(r"\{\{[^}]+\}\}")

SYSTEM = (
    "You translate user-interface strings for a job-discovery web application. "
    "Translate each English value into {language}. Keep it short and natural for "
    "UI labels; never add explanations. Preserve every {{{{placeholder}}}} exactly. "
    "Keep product and brand names, file formats and technical acronyms untranslated "
    "(e.g. Neuronection, Career Assistant, GitHub, LinkedIn, OpenAI, ATS, CV, PDF, API). "
    "Keep numbers, dates and punctuation shapes intact. Reply with a JSON object "
    "mapping the SAME keys to translated values and nothing else."
)


def flatten(node: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten(value, path))
        else:
            out[path] = value
    return out


def unflatten(flat: dict[str, str]) -> dict:
    root: dict = {}
    for path, value in flat.items():
        node = root
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return root


def ask(language: str, items: dict[str, str]) -> dict[str, str]:
    body = json.dumps(
        {
            "model": MODEL,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2, "num_ctx": 8192},
            "messages": [
                {"role": "system", "content": SYSTEM.format(language=language)},
                {
                    "role": "user",
                    "content": json.dumps(items, ensure_ascii=False, indent=0),
                },
            ],
        }
    ).encode()
    request = urllib.request.Request(
        OLLAMA, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.load(response)
    content = payload["message"]["content"].strip()
    start, end = content.find("{"), content.rfind("}")
    return json.loads(content[start : end + 1])


def placeholders_ok(source: str, translated: str) -> bool:
    return sorted(PLACEHOLDER.findall(source)) == sorted(PLACEHOLDER.findall(translated))


def translate(locale: str, language: str, only_missing: bool) -> None:
    source = flatten(json.loads((LOCALES / "en.json").read_text()))
    target_path = LOCALES / f"{locale}.json"
    existing = flatten(json.loads(target_path.read_text())) if target_path.is_file() else {}
    pending = {
        key: value
        for key, value in source.items()
        if isinstance(value, str)
        and not (only_missing and existing.get(key))
    }
    keys = list(pending)
    translated = dict(existing)
    failures = 0
    for offset in range(0, len(keys), BATCH):
        chunk = keys[offset : offset + BATCH]
        items = {key: pending[key] for key in chunk}
        for attempt in range(3):
            try:
                result = ask(language, items)
                break
            except Exception as error:  # noqa: BLE001 - retry any transport/parse error
                print(f"  retry {locale} batch {offset} ({error})", flush=True)
                result = {}
        for key in chunk:
            value = result.get(key)
            if not isinstance(value, str) or not value.strip():
                value = existing.get(key, "")
                if not value:
                    failures += 1
                continue
            if not placeholders_ok(pending[key], value):
                value = existing.get(key, "")
                if not value:
                    failures += 1
                continue
            translated[key] = value.strip()
        done = min(offset + BATCH, len(keys))
        print(f"{locale}: {done}/{len(keys)} (failures {failures})", flush=True)
    ordered = {key: translated.get(key, source[key]) for key in source}
    missing = [key for key, value in ordered.items() if not value]
    target_path.write_text(
        json.dumps(unflatten(ordered), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{locale}: wrote {len(ordered)} keys, {len(missing)} missing", flush=True)


if __name__ == "__main__":
    locale = sys.argv[1]
    language = {"de": "German", "el": "Greek"}[locale]
    translate(locale, language, only_missing="--missing" in sys.argv)
