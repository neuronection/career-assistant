import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { Account } from "@/pages/settings/Account";
import { setAppLocale } from "@/lib/i18n";
import i18next from "i18next";

const setMyLocale = vi.fn(async (locale: string) => ({ locale, supported: ["en", "de", "el"] }));

vi.mock("@/api/admin", () => ({
  changeMyPassword: vi.fn(),
  deleteMyAccount: vi.fn(),
  listMySessions: vi.fn(async () => []),
  revokeMySession: vi.fn(),
}));

vi.mock("@/api/i18n", () => ({
  fetchLocale: vi.fn(async () => ({ locale: "en", supported: ["en", "de", "el"] })),
  setMyLocale: (locale: string) => setMyLocale(locale),
  fetchInstanceLocale: vi.fn(async () => ({ locale: "en", supported: ["en", "de", "el"] })),
  setInstanceLocale: vi.fn(async (locale: string) => ({ locale, supported: ["en", "de", "el"] })),
}));

afterEach(async () => {
  await setAppLocale("en");
});

describe("locale switcher", () => {
  test("choosing German persists and updates i18next + html lang", async () => {
    render(<Account />);
    const german = await screen.findByTestId("locale-de");
    await userEvent.click(german);

    await waitFor(() => expect(setMyLocale).toHaveBeenCalledWith("de"));
    await waitFor(() => expect(document.documentElement.lang).toBe("de"));
    expect(i18next.language).toBe("de");
    expect(screen.getByText("Aussehen")).toBeInTheDocument();
  });
});
