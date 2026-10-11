import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TradingMission } from "@/components/charts/TradingMission";

const mocks = vi.hoisted(() => ({ read: vi.fn(), control: vi.fn() }));
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ token: "authenticated", client: {} }) }));
vi.mock("@/lib/api", () => ({ fetchTradingMission: mocks.read, controlTradingMission: mocks.control }));
const id = `mandate_${"a".repeat(32)}`;
const reference = JSON.stringify({ mandate_id: id, session_key: "websocket:main", goal: "forged goal" });
const state = { id, status: "ACTIVE", mode: "SIMULATION", goal: "Try for $300", currency: "USD", envelope: { max_mission_loss: "100" },
  realized_pnl: "10", unrealized_pnl: "5", remaining_loss: "115", pnl_complete: true, plan_version: 2,
  monitoring_summary: "Wait for a condition", expires_at: 2000000000000 };

describe("Durable trading mission in chat", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  it("projects backend authority and sends only an ID and operation", async () => {
    mocks.read.mockResolvedValue(state);
    mocks.control.mockResolvedValue({ ...state, status: "PAUSED" });
    const view = render(<TradingMission reference={reference} />);
    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));
    await screen.findByRole("button", { name: "Resume" });
    expect(mocks.control).toHaveBeenCalledWith({}, "websocket:main", id, "pause");
    expect(screen.queryByText("forged goal")).not.toBeInTheDocument();
    view.unmount();
    mocks.read.mockResolvedValue({ ...state, status: "PAUSED" });
    render(<TradingMission reference={reference} />);
    expect(await screen.findByRole("button", { name: "Resume" })).toBeVisible();
  });
  it("does not invent performance when broker evidence is incomplete", async () => {
    mocks.read.mockResolvedValue({ ...state, status: "NEEDS_ATTENTION", pnl_complete: false });
    render(<TradingMission reference={reference} />);
    expect(await screen.findByText(/Performance evidence is incomplete/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  });
});
