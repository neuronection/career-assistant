export const AI_CAPS = ["text", "vision", "tools", "embeddings", "audio"] as const;

export type AiCap = (typeof AI_CAPS)[number];

const EMBEDDING_HINTS = ["embed", "bge", "gte", "minilm", "jina"];
const AUDIO_HINTS = ["whisper", "tts", "audio", "speech", "voice"];
const VISION_HINTS = ["vision", "-vl", "llava", "image", "omni"];

export function guessCaps(modelId: string): AiCap[] {
  const id = modelId.toLowerCase();
  if (EMBEDDING_HINTS.some((hint) => id.includes(hint))) return ["embeddings"];
  if (AUDIO_HINTS.some((hint) => id.includes(hint))) return ["audio"];
  if (VISION_HINTS.some((hint) => id.includes(hint))) return ["text", "vision"];
  return ["text"];
}
