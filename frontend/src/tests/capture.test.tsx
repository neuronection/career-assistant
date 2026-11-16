import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { CaptureDialog } from "@/features/postings/components/CaptureDialog";
import { CaptureHelpPage } from "@/features/postings/pages/CaptureHelpPage";
import { capturePosting } from "@/api/postings";

vi.mock("@/api/postings", () => ({
  capturePosting: vi.fn(),
}));

const onCaptured = vi.fn();

describe("capture", () => {
  beforeEach(() => {
    vi.mocked(capturePosting).mockResolvedValue({ id: "p1", ref: "CAP123", created: true });
    onCaptured.mockReset();
  });

  it("confirms the prefilled URL and hands back the ref", async () => {
    render(
      <MemoryRouter>
        <CaptureDialog
          open
          initialUrl="https://jobs.example/1"
          onClose={vi.fn()}
          onCaptured={onCaptured}
        />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("capture-url")).toHaveValue("https://jobs.example/1");
    fireEvent.click(screen.getByTestId("capture-confirm"));
    await waitFor(() =>
      expect(capturePosting).toHaveBeenCalledWith("https://jobs.example/1"),
    );
    expect(onCaptured).toHaveBeenCalledWith("CAP123");
  });

  it("shows the guard error instead of capturing", async () => {
    vi.mocked(capturePosting).mockRejectedValue(new Error("private address"));
    render(
      <MemoryRouter>
        <CaptureDialog
          open
          initialUrl="http://127.0.0.1/job"
          onClose={vi.fn()}
          onCaptured={onCaptured}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("capture-confirm"));
    expect(await screen.findByTestId("capture-error")).toBeInTheDocument();
    expect(onCaptured).not.toHaveBeenCalled();
  });

  it("renders the draggable bookmarklet help", () => {
    render(
      <MemoryRouter>
        <CaptureHelpPage />
      </MemoryRouter>,
    );
    const bookmarklet = screen.getByTestId("capture-bookmarklet");
    expect(bookmarklet).toHaveAttribute("draggable", "true");
    expect(bookmarklet.getAttribute("href")).toContain("/postings?capture=");
  });
});
