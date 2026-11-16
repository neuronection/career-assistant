import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, type AxiosResponse } from "axios";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@neuronection/assistant-ui";

import {
  fetchParseView,
  resetCvStudioMocks,
} from "@/tests/cvStudioHarness";
import { CvBuilder } from "@/features/cv/pages/CvBuilder";
import { CvTemplateEditor } from "@/features/cv/pages/CvTemplateEditor";

function axiosFailure(status: number, detail: string): AxiosError {
  const response = {
    status,
    statusText: "Service Unavailable",
    data: { detail },
    headers: {},
    config: {},
  } as unknown as AxiosResponse;
  return new AxiosError(
    `Request failed with status code ${status}`,
    "ERR_BAD_RESPONSE",
    undefined,
    undefined,
    response,
  );
}

function renderBuilder() {
  return render(
    <TooltipProvider>
      <MemoryRouter initialEntries={["/cv/cv-1"]}>
        <Routes>
          <Route path="/cv/:id" element={<CvBuilder />} />
          <Route path="/cv/templates/:id" element={<CvTemplateEditor />} />
        </Routes>
      </MemoryRouter>
    </TooltipProvider>
  );
}

beforeEach(resetCvStudioMocks);

describe("Parse view (plan 212 S1.2)", () => {
  it("opens from the toolbar, shows findings, pages and the disclaimer", async () => {
    renderBuilder();
    await screen.findByTestId("builder-toolbar");
    await userEvent.click(screen.getByTestId("parse-view-button"));
    await waitFor(() => expect(fetchParseView).toHaveBeenCalledWith("cv-1"));
    expect(await screen.findByTestId("parse-view-disclaimer")).toHaveTextContent(
      /our own extractor/i,
    );
    expect(screen.getByTestId("parse-view-text-layer")).toHaveTextContent(/text layer present/i);
    expect(screen.getByTestId("parse-view-findings")).toBeInTheDocument();
    expect(screen.getByTestId("parse-view-finding-welded_lines")).toBeInTheDocument();
    expect(screen.getByTestId("parse-view-page-0")).toHaveTextContent(/Built the thing/);
    // No score anywhere on this surface.
    expect(screen.queryByTestId("parse-view-score")).not.toBeInTheDocument();
  });

  it("surfaces the capability message when the engine is unavailable", async () => {
    fetchParseView.mockRejectedValue(
      axiosFailure(503, "Server PDF engine not installed — use the print view instead"),
    );
    renderBuilder();
    await screen.findByTestId("builder-toolbar");
    fireEvent.click(screen.getByTestId("parse-view-button"));
    const error = await screen.findByTestId("parse-view-error");
    expect(error).toHaveTextContent(/print view/i);
  });

  it("shows a clean state when there are no findings", async () => {
    fetchParseView.mockResolvedValue({
      pages: [{ index: 0, text: "Experience", line_count: 1 }],
      findings: [],
      page_count: 1,
      text_layer: true,
      engine: "pdf",
    });
    renderBuilder();
    await screen.findByTestId("builder-toolbar");
    fireEvent.click(screen.getByTestId("parse-view-button"));
    expect(await screen.findByTestId("parse-view-body")).toHaveTextContent(/No findings/i);
  });
});
