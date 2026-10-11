import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ActionApproval } from "@/components/charts/ActionApproval";
import { LtrText } from "@/components/LtrText";
import { setAppLanguage } from "@/i18n";
import { localeDirection, normalizeLocale, resolveInitialLocale, LOCALE_STORAGE_KEY } from "@/i18n/config";

const mocks = vi.hoisted(() => ({ read: vi.fn(), resolve: vi.fn(), edit: vi.fn() }));
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ token: "authenticated", client: {} }) }));
vi.mock("@/lib/api", () => ({
  fetchActionApproval: mocks.read,
  resolveActionApproval: mocks.resolve,
  editActionApproval: mocks.edit,
}));

const id = `approval_${"c".repeat(32)}`;
const reference = JSON.stringify({ approval_id: id, session_key: "websocket:main" });

describe("Arabic and RTL", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    localStorage.removeItem(LOCALE_STORAGE_KEY);
    await setAppLanguage("en");
  });

  it("maps Arabic device tags and sets document direction", async () => {
    expect(normalizeLocale("ar-EG")).toBe("ar");
    expect(localeDirection("ar")).toBe("rtl");
    expect(localeDirection("en")).toBe("ltr");
    await setAppLanguage("ar");
    expect(document.documentElement.lang).toBe("ar");
    expect(document.documentElement.dir).toBe("rtl");
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("ar");
  });

  it("keeps the product in English until a stored or device locale says otherwise", () => {
    expect(resolveInitialLocale()).toBe("en");
    localStorage.setItem(LOCALE_STORAGE_KEY, "ar-SA");
    expect(resolveInitialLocale()).toBe("ar");
  });

  it("localizes an approval and isolates financial tokens", async () => {
    mocks.read.mockResolvedValue({
      id,
      status: "PENDING",
      action: {
        account_id: "acct-1",
        broker_symbol: "XAUUSD",
        intent: {
          operation: "open",
          side: "buy",
          order_type: "market",
          volume: "0.10",
          price: "82,950.34",
          stop_loss: "82,100",
          take_profit: "84,200",
        },
      },
    });
    await setAppLanguage("ar");
    render(<ActionApproval reference={reference} />);
    expect(await screen.findByRole("button", { name: "موافقة" })).toBeVisible();
    expect(screen.getByRole("button", { name: "رفض" })).toBeVisible();
    expect(screen.getByText("طلب شراء")).toBeVisible();
    const symbol = screen.getByText("XAUUSD");
    expect(symbol.closest("bdi")).toHaveAttribute("dir", "ltr");
    const price = screen.getByText("82,950.34");
    expect(price.closest("bdi")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText("acct-1").closest("bdi")).toHaveAttribute("dir", "ltr");
  });

  it("renders an explicit LTR island", () => {
    render(<LtrText>BTCUSDTm</LtrText>);
    expect(screen.getByText("BTCUSDTm").closest("bdi")).toHaveAttribute("dir", "ltr");
  });
});

describe("narrow approval layout", () => {
  beforeEach(async () => {
    await setAppLanguage("en");
  });

  it("does not use a horizontal page scroll for the approval card", async () => {
    mocks.read.mockResolvedValue({
      id,
      status: "PENDING",
      action: { broker_symbol: "EURUSD", account_id: "demo", intent: { operation: "open", side: "sell", volume: "1" } },
    });
    render(<ActionApproval reference={reference} />);
    const card = await screen.findByRole("region", { name: "Action approval" });
    expect(card.className).not.toMatch(/overflow-x-auto|min-w-\[/);
    await waitFor(() => expect(screen.getByText("EURUSD")).toBeVisible());
  });
});
