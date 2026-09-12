import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ProtectedRoute } from "@/components/ProtectedRoute";

describe("ProtectedRoute", () => {
  it("renders children (single-user mode: no auth wall)", () => {
    render(
      <MemoryRouter initialEntries={["/private"]}>
        <ProtectedRoute>
          <div>secret content</div>
        </ProtectedRoute>
      </MemoryRouter>
    );
    expect(screen.getByText("secret content")).toBeInTheDocument();
  });
});
