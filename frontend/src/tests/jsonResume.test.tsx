import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { JsonResumeCard } from "@/components/profile/JsonResumeCard";
import { exportJsonResume, importJsonResume } from "@/api/jsonResume";

vi.mock("@/api/jsonResume", () => ({
  exportJsonResume: vi.fn(),
  importJsonResume: vi.fn(),
}));

const REPORT = {
  mapped: {
    basics: { full_name: "Ada" },
    work: [{ title: "Engineer" }],
    education: [{ institution: "Uni" }],
    skills: [],
  },
  dropped: ["unknownField"],
  warnings: ["skills are reported only"],
  basics_conflicts: [{ field: "full_name", current: "Old", incoming: "Ada" }],
  applied: false,
  created: { work: 0, education: 0 },
};

describe("JsonResumeCard", () => {
  beforeEach(() => {
    vi.mocked(exportJsonResume).mockResolvedValue({ basics: { name: "Ada" } });
    vi.mocked(importJsonResume).mockResolvedValue(REPORT);
  });

  it("previews a file, reports dropped keys and applies", async () => {
    render(<JsonResumeCard />);
    const file = new File(['{"basics":{"name":"Ada"}}'], "resume.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", {
      value: async () => '{"basics":{"name":"Ada"},"unknownField":1}',
    });
    fireEvent.change(screen.getByTestId("import-review-file-input"), {
      target: { files: [file] },
    });
    expect(await screen.findByTestId("import-review-report")).toHaveTextContent(
      "Work",
    );
    expect(screen.getByTestId("import-review-dropped")).toHaveTextContent("unknownField");

    fireEvent.click(screen.getByTestId("import-review-apply"));
    await waitFor(() =>
      expect(importJsonResume).toHaveBeenLastCalledWith(
        { basics: { name: "Ada" }, unknownField: 1 },
        true,
      ),
    );
  });

  it("exports the profile as a download", async () => {
    const create = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { value: create, configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
    render(<JsonResumeCard />);
    fireEvent.click(screen.getByTestId("json-resume-export"));
    await waitFor(() => expect(exportJsonResume).toHaveBeenCalled());
    expect(create).toHaveBeenCalled();
  });
});
