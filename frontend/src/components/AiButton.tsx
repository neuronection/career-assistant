import { useState } from "react";
import { quickAssist } from "@/api/universities";
import { apiDetail } from "@/api/client";
import { AiButton as LibraryAiButton } from "@neuronection/assistant-ui";

const SUGGESTED: Record<string, string[]> = {
  job_detail: ["Why does this match me?", "What would I study for this?", "What are the downsides?"],
  rankings: ["Why is this ranked highly?", "What similar jobs exist?"],
  catalog: ["Which family fits a creative person?", "What jobs need math?"],
};

export function AiButton({
  jobCode,
  page,
  question,
  label,
}: {
  jobCode?: string;
  page: string;
  question?: string;
  label?: string;
}) {
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const suggestions = question ? [question] : SUGGESTED[page] ?? ["Tell me more"];

  return (
    <LibraryAiButton
      label={label ?? "Ask AI"}
      suggestions={suggestions}
      loading={loading}
      error={error}
      onResponse={
        answer && !loading ? (
          <p className="text-sm text-slate-700 whitespace-pre-wrap">{answer}</p>
        ) : null
      }
      onSubmit={async (prompt) => {
        setLoading(true);
        setError("");
        try {
          const result = await quickAssist({ question: prompt, page, job_code: jobCode });
          setAnswer(result.answer);
        } catch (err) {
          setError(apiDetail(err));
        } finally {
          setLoading(false);
        }
      }}
    />
  );
}
