export const AI_CAPS = ["text", "vision", "tools", "embeddings", "stt", "tts", "decision"] as const;

export type AiCap = (typeof AI_CAPS)[number];

const EMBEDDING_HINTS = ["embed", "bge", "gte", "minilm", "jina"];
const STT_HINTS = ["whisper", "transcribe", "stt"];
const TTS_HINTS = ["tts", "speech", "voice"];
const VISION_HINTS = ["vision", "-vl", "llava", "image", "omni"];

// §15 split: stt/tts are distinct capabilities; `decision` is explicit-only
// (never guessed from a model name — D1).
export function guessCaps(modelId: string): AiCap[] {
  const id = modelId.toLowerCase();
  if (EMBEDDING_HINTS.some((hint) => id.includes(hint))) return ["embeddings"];
  if (STT_HINTS.some((hint) => id.includes(hint))) return ["stt"];
  if (TTS_HINTS.some((hint) => id.includes(hint))) return ["tts"];
  if (VISION_HINTS.some((hint) => id.includes(hint))) return ["text", "vision"];
  return ["text"];
}
