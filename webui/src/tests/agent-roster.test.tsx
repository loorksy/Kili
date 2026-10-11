import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentRoster } from "@/components/AgentRoster";

const mocks = vi.hoisted(() => ({ read: vi.fn(), createAgent: vi.fn(), createGroup: vi.fn(), change: vi.fn() }));
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ token: "authenticated", client: {} }) }));
vi.mock("@/lib/api", () => ({
  fetchAgentRoster: mocks.read,
  createKiliAgent: mocks.createAgent,
  createKiliGroup: mocks.createGroup,
  changeKiliGroupMember: mocks.change,
}));

describe("Agent roster", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  it("creates an agent and opens its own conversation", async () => {
    const created = { id: "agent_a", name: "Ada", instructions: "Watch gold.", session_key: "websocket:agent_a" };
    mocks.read.mockResolvedValueOnce({ agents: [], groups: [] }).mockResolvedValue({ agents: [created], groups: [] });
    mocks.createAgent.mockResolvedValue(created);
    const onOpen = vi.fn();
    render(<AgentRoster onOpen={onOpen} />);
    expect(await screen.findByText("No agents yet.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Agent name"), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText("Instructions"), { target: { value: "Watch gold." } });
    fireEvent.click(screen.getByRole("button", { name: "Save agent" }));
    expect(await screen.findByRole("button", { name: "Ada" })).toBeVisible();
    expect(mocks.createAgent).toHaveBeenCalledWith({}, "Ada", "Watch gold.");
    expect(onOpen).toHaveBeenCalledWith("websocket:agent_a");
    expect(screen.queryByText(/\/approve/)).not.toBeInTheDocument();
  });
});
