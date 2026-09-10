"""Speech-to-text for the dictation task.

Audio transcription is not a LangChain chat-model capability, so — like
study's reference implementation this ports — it talks to the provider
REST APIs directly, through the same resolved task model the gateway
uses. Capability is enforced at call time: unsupported providers raise
:class:`TranscriptionUnsupported` instead of being unassignable.
"""

import base64

import httpx

from app.ai.providers.resolution import ResolvedModel

EXT_BY_MIME: dict[str, str] = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/flac": "flac",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
}

DEFAULT_TRANSCRIBE_INSTRUCTION = (
    "Transcribe the attached audio exactly as spoken. Output ONLY the transcript."
)


class TranscriptionUnsupported(RuntimeError):
    def __init__(self, provider_type: str) -> None:
        super().__init__(
            f"provider '{provider_type}' does not offer speech-to-text — assign an "
            "OpenAI-compatible (Whisper) or Google model for the transcribe task"
        )
        self.provider_type = provider_type


def audio_extension(mime: str) -> str:
    return EXT_BY_MIME.get(mime.split(";")[0].strip().lower(), "webm")


def transcribe_with(
    client: httpx.Client,
    resolved: ResolvedModel,
    data: bytes,
    mime: str,
    language: str | None,
) -> str:
    if mime.startswith("video/") and resolved.provider_type == "google":
        raise TranscriptionUnsupported(resolved.provider_type)
    if resolved.provider_type == "openai_compatible":
        return _transcribe_openai(client, resolved, data, mime, language)
    if resolved.provider_type == "google":
        return _transcribe_google(client, resolved, data)
    raise TranscriptionUnsupported(resolved.provider_type)


def _transcribe_openai(
    client: httpx.Client,
    resolved: ResolvedModel,
    data: bytes,
    mime: str,
    language: str | None,
) -> str:
    form: list[tuple[str, tuple[str | None, bytes | str]]] = [
        ("model", (None, resolved.model_name)),
        ("response_format", (None, "json")),
        ("file", (f"audio.{audio_extension(mime)}", data)),
    ]
    if language:
        form.append(("language", (None, language)))
    response = client.post(
        f"{resolved.base_url}/audio/transcriptions",
        headers={"Authorization": f"Bearer {resolved.api_key}"}
        if resolved.api_key
        else {},
        files=form,
    )
    response.raise_for_status()
    return str(response.json().get("text", "")).strip()


def _transcribe_google(
    client: httpx.Client,
    resolved: ResolvedModel,
    data: bytes,
) -> str:
    response = client.post(
        f"{resolved.base_url}/v1beta/models/{resolved.model_name}:generateContent",
        params={"key": resolved.api_key},
        json={
            "systemInstruction": {"parts": [{"text": DEFAULT_TRANSCRIBE_INSTRUCTION}]},
            "contents": [
                {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "audio/webm",
                                "data": base64.b64encode(data).decode("ascii"),
                            }
                        },
                        {"text": "Transcribe this audio."},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0},
        },
    )
    response.raise_for_status()
    body = response.json()
    return "".join(
        str(part.get("text", ""))
        for part in (
            body.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        )
    ).strip()
