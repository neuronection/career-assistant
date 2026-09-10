import type { AiToolArgument, AiToolInfo } from "@/api/ai";
import type { ChatToolCatalogEntry } from "@/components/ui/chat";

export function toolArguments(tool: AiToolInfo): AiToolArgument[] {
  const properties = tool.input_schema?.properties ?? {};
  const required = tool.input_schema?.required ?? [];
  return Object.entries(properties).map(([name, spec]) => ({
    name,
    type: spec.type ?? "any",
    required: required.includes(name),
    description: spec.description ?? null,
  }));
}

export function toolCatalogEntry(tool: AiToolInfo): ChatToolCatalogEntry {
  return {
    name: tool.key,
    title: tool.title,
    description: tool.description,
    arguments: toolArguments(tool),
    scope: tool.scope,
  };
}
