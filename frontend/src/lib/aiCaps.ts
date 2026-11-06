export const AI_CAPS = ["text", "vision", "tools", "embeddings", "stt", "tts", "decision"] as const;

export type AiCap = (typeof AI_CAPS)[number];

const EMBEDDING_HINTS = ["embed", "bge", "gte", "minilm", "jina"];
const STT_HINTS = ["whisper", "transcribe", "stt"];
const TTS_HINTS = ["tts", "speech", "voice"];
// Mirrors the backend's infer_caps hint tables (family §15 law) — vision
// families and tool-capable lines evolve per generation, so both tables
// gain entries alongside the presets.
const VISION_HINTS = [
  "gemini",
  "gpt-4o",
  "gpt-4.1",
  "gpt-4-turbo",
  "gpt-5",
  "gpt-6",
  "claude",
  "vision",
  "-vl",
  "llava",
  "pixtral",
  "gemma3",
  "image",
  "omni",
];
const TOOL_HINTS = [
  "gpt-4",
  "gpt-5",
  "gpt-6",
  "o3",
  "o4",
  "claude",
  "gemini",
  "deepseek",
  "qwen",
  "mistral",
  "llama",
];

// §15 split: stt/tts are distinct capabilities; `decision` is explicit-only
// (never guessed from a model name — D1).
export function guessCaps(modelId: string): AiCap[] {
  const id = modelId.toLowerCase();
  if (EMBEDDING_HINTS.some((hint) => id.includes(hint))) return ["embeddings"];
  if (STT_HINTS.some((hint) => id.includes(hint))) return ["stt"];
  if (TTS_HINTS.some((hint) => id.includes(hint))) return ["tts"];
  const caps: AiCap[] = ["text"];
  if (VISION_HINTS.some((hint) => id.includes(hint))) caps.push("vision");
  if (TOOL_HINTS.some((hint) => id.includes(hint))) caps.push("tools");
  return caps;
}
