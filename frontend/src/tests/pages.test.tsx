import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Login } from "@/pages/Login";
import { Register } from "@/pages/Register";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { useAuthStore } from "@/stores/authStore";

describe("Login page", () => {
  it("renders email and password fields", () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );
    expect(screen.getByPlaceholderText("Email")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });
});

describe("Register page", () => {
  it("renders registration fields and link to login", () => {
    render(
      <MemoryRouter>
        <Register />
      </MemoryRouter>
    );
    expect(screen.getByPlaceholderText(/full name/i)).toBeInTheDocument();
    expect(screen.getByText(/have an account/i)).toBeInTheDocument();
  });
});

describe("ProtectedRoute", () => {
  it("hides children without a token", () => {
    useAuthStore.setState({ token: null });
    render(
      <MemoryRouter initialEntries={["/private"]}>
        <ProtectedRoute>
          <div>secret content</div>
        </ProtectedRoute>
      </MemoryRouter>
    );
    expect(screen.queryByText("secret content")).toBeNull();
  });

  it("shows children with a token", () => {
    useAuthStore.setState({ token: "tok" });
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
