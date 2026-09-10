import {
  buildChatMarkdown,
  chatExportFileName,
  downloadChatMarkdown,
} from "@/components/ui/chat";
import { fetchMessages } from "@/api/universities";
import type { ChatMessage } from "@/types";

/** Career's annotations as library blockquote lines. */
export function buildChatMarkdownFromRows(title: string, messages: ChatMessage[]): string {
  return buildChatMarkdown(title, messages, {
    assistantLabel: "Career Assistant",
    annotations: (message) => {
      if (message.role !== "assistant") {
        return [];
      }
      const meta = (message as ChatMessage).metadata_json;
      const codes = meta?.referenced_job_codes ?? [];
      const refs = meta?.referenced_posting_refs ?? [];
      const parts: string[] = [];
      if (codes.length > 0) {
        parts.push(`jobs: ${codes.join(", ")}`);
      }
      if (refs.length > 0) {
        parts.push(`postings: ${refs.join(", ")}`);
      }
      return parts.length > 0 ? [parts.join(" · ")] : [];
    },
  });
}

/** Export a conversation as Markdown. */
export async function exportChatMarkdown(sessionId: string, title: string): Promise<void> {
  const messages = await fetchMessages(sessionId);
  downloadChatMarkdown(buildChatMarkdownFromRows(title, messages), chatExportFileName(title));
}
