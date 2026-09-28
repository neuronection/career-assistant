import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AxiosError, type AxiosResponse } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as authApi from "@/api/auth";
import { LoginScreen } from "@/components/auth/LoginScreen";
import { useAuthStore } from "@/stores/authStore";

vi.mock("@/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/auth")>();
  return {
    ...actual,
    fetchMe: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  };
});

const mocked = vi.mocked(authApi);

function axiosFailure(status: number, detail: string): AxiosError {
  const response = {
    status,
    statusText: "Error",
    data: { detail },
    headers: {},
    config: {},
  } as unknown as AxiosResponse;
  return new AxiosError(
    `Request failed with status code ${status}`,
    "ERR_BAD_REQUEST",
    undefined,
    undefined,
    response,
  );
}

const USER = {
  id: "u-1",
  email: "ada@example.com",
  full_name: "Ada Lovelace",
  is_active: true,
  is_admin: false,
};

describe("LoginScreen (§12 login/register)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: null, loading: false, status: "anonymous", error: null });
  });

  it("sign-in failure keeps the form and shows the login error", async () => {
    mocked.login.mockRejectedValue(new Error("nope"));
    render(<LoginScreen />);
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "whatever" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(
      await screen.findByText("Sign-in failed. Check your email and password."),
    ).toBeInTheDocument();
    expect(useAuthStore.getState().status).toBe("anonymous");
  });

  it("the register mode exposes full name and the length hint", async () => {
    mocked.register.mockResolvedValue(USER);
    render(<LoginScreen />);
    fireEvent.click(screen.getByRole("button", { name: "No account?" }));
    expect(screen.getByLabelText("Full name")).toBeInTheDocument();
    expect(screen.getByText("At least 10 characters.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Full name"), {
      target: { value: "Ada Lovelace" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "long-enough-123" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "long-enough-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    await waitFor(() => expect(useAuthStore.getState().status).toBe("authenticated"));
    expect(mocked.register).toHaveBeenCalledWith({
      email: "ada@example.com",
      password: "long-enough-123",
      full_name: "Ada Lovelace",
    });
  });

  it("a confirm mismatch blocks the register call", async () => {
    mocked.register.mockResolvedValue(USER);
    render(<LoginScreen />);
    fireEvent.click(screen.getByRole("button", { name: "No account?" }));
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "long-enough-123" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "something-else" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
    expect(mocked.register).not.toHaveBeenCalled();
  });

  it("registration-disabled instances (403) hide the register action", async () => {
    mocked.register.mockRejectedValue(
      axiosFailure(403, "Registration is disabled"),
    );
    render(<LoginScreen />);
    fireEvent.click(screen.getByRole("button", { name: "No account?" }));
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "long-enough-123" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "long-enough-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    expect(
      await screen.findByText(
        "Registration is disabled on this instance — ask an administrator to create your account.",
      ),
    ).toBeInTheDocument();
    // the register action is gone; login stays
    expect(screen.queryByRole("button", { name: "No account?" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Register" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(useAuthStore.getState().status).toBe("anonymous");
  });

  it("a plain register failure keeps the register action available", async () => {
    mocked.register.mockRejectedValue(axiosFailure(409, "Email already registered"));
    render(<LoginScreen />);
    fireEvent.click(screen.getByRole("button", { name: "No account?" }));
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "long-enough-123" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "long-enough-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    expect(
      await screen.findByText("Registration failed — the email may already be in use."),
    ).toBeInTheDocument();
    // still in register mode: the register action stays available
    expect(screen.getByRole("button", { name: "Have an account?" })).toBeInTheDocument();
  });
});
