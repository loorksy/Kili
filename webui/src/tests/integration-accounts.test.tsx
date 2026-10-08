import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IntegrationSettings } from "@/components/settings/system/IntegrationSettings";

const mocks = vi.hoisted(() => ({ read: vi.fn(), save: vi.fn(), map: vi.fn(), autonomy: vi.fn() }));
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ token: "authenticated", client: {} }) }));
vi.mock("@/lib/api", () => ({ fetchIntegrationSettings: mocks.read, configureIntegration: mocks.save,
  configureInstrumentMapping: mocks.map, configureAutonomousTrading: mocks.autonomy }));
const status = { charts_enabled: true, oanda: { configured: false }, metaapi: { configured: true, account_id: "first" },
  accounts: [{ account_id: "first", name: "Personal", environment: "practice", region: "london", default: true },
    { account_id: "second", name: "Research", environment: "practice", region: "new-york", default: false }] };

describe("Existing connection settings with multiple broker accounts", () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.read.mockResolvedValue(status); mocks.save.mockResolvedValue(status); });
  it("edits an exact saved account without displaying its stored credential", async () => {
    render(<IntegrationSettings />);
    expect(screen.queryByRole("option", { name: "OANDA" })).not.toBeInTheDocument();
    await screen.findByRole("option", { name: "Research" });
    fireEvent.change(screen.getByLabelText("Saved broker account"), { target: { value: "second" } });
    expect(screen.getByLabelText("Connection account")).toHaveValue("second");
    expect(screen.getByLabelText("Broker account name")).toHaveValue("Research");
    expect(screen.getByLabelText("Connection credential")).toHaveValue("");
    expect(screen.getByLabelText("Default broker account")).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Save connection" }));
    await waitFor(() => expect(mocks.save).toHaveBeenCalledWith({}, expect.objectContaining({
      provider: "metaapi", account_id: "second", name: "Research", token: null, make_default: false, region: "new-york",
    })));
  });
  it("clears credential entry when switching accounts and binds symbol confirmation to the selected account", async () => {
    render(<IntegrationSettings />);
    expect(screen.queryByRole("option", { name: "OANDA" })).not.toBeInTheDocument();
    await screen.findByRole("option", { name: "Research" });
    fireEvent.change(screen.getByLabelText("Connection credential"), { target: { value: "temporary-secret" } });
    fireEvent.change(screen.getByLabelText("Saved broker account"), { target: { value: "second" } });
    expect(screen.getByLabelText("Connection credential")).toHaveValue("");
    fireEvent.change(screen.getByPlaceholderText("GOLD / XAUUSDm / …"), { target: { value: "GOLDm" } });
    fireEvent.change(screen.getByLabelText("Canonical instrument"), { target: { value: "gold" } });
    mocks.map.mockResolvedValue({});
    fireEvent.click(screen.getByRole("button", { name: "Confirm and verify" }));
    await waitFor(() => expect(mocks.map).toHaveBeenCalledWith({}, expect.objectContaining({ account_id: "second", broker_symbol: "GOLDm" })));
  });
});
