import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ActionApproval } from "@/components/charts/ActionApproval";

const mocks = vi.hoisted(() => ({ read: vi.fn(), resolve: vi.fn() }));
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ token: "authenticated", client: {} }) }));
vi.mock("@/lib/api", () => ({ fetchActionApproval: mocks.read, resolveActionApproval: mocks.resolve }));
const id = `approval_${"a".repeat(32)}`;
const reference = JSON.stringify({ approval_id: id, session_key: "websocket:main", action: { volume: "forged benign payload" } });

describe("Backend-owned approval", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  it("shows authoritative action before allowing resolution and ignores model-supplied details", async () => {
    mocks.read.mockResolvedValue({ id, status: "PENDING", action: { volume: "0.10", broker_symbol: "GOLDm" } });
    mocks.resolve.mockResolvedValue({ id, status: "APPROVED" });
    render(<ActionApproval reference={reference} />);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await screen.findByText("Approved");
    expect(screen.queryByText(/forged benign/)).not.toBeInTheDocument();
    expect(mocks.resolve).toHaveBeenCalledWith({}, "websocket:main", id, true);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });
  it("fails closed when the record is unavailable", async () => {
    mocks.read.mockRejectedValue(new Error("gone"));
    render(<ActionApproval reference={reference} />);
    await screen.findByText("Approval unavailable or expired");
    expect(mocks.resolve).not.toHaveBeenCalled();
  });
  it("restores consumed state rather than offering another approval", async () => {
    mocks.read.mockResolvedValue({ id, status: "CONSUMED", action: {} });
    render(<ActionApproval reference={reference} />);
    await waitFor(() => expect(screen.getByText("CONSUMED")).toBeVisible());
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });
});
