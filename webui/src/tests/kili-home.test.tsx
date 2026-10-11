import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KiliHome } from "@/components/KiliHome";

const mocks = vi.hoisted(() => ({ home: vi.fn(), createAgent: vi.fn(), createGroup: vi.fn() }));
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ token: "authenticated", client: {} }) }));
vi.mock("@/lib/api", () => ({
  fetchHome: mocks.home,
  createKiliAgent: mocks.createAgent,
  createKiliGroup: mocks.createGroup,
}));

describe("Kili home", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  it("opens a two-item create menu and a bot form without a computer", async () => {
    mocks.home.mockResolvedValue({ items: [], filters: ["all", "messages", "bots", "groups", "files", "routines"] });
    render(<KiliHome onOpenSession={vi.fn()} onOpenSettings={vi.fn()} />);
    expect(await screen.findByText("No bots yet.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "+" }));
    expect(screen.getByRole("button", { name: "New Bot" })).toBeVisible();
    expect(screen.getByRole("button", { name: "New Group Chat" })).toBeVisible();
    expect(screen.getAllByRole("button").filter(button => button.textContent === "New Bot" || button.textContent === "New Group Chat")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "New Bot" }));
    expect(screen.getByLabelText("Name your Bot")).toBeVisible();
    expect(screen.getByRole("button", { name: "Create" })).toBeVisible();
    expect(screen.queryByText("Bot Computer")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByText(/No per-bot computer/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Download the app" })).toHaveAttribute("href", "/downloads/kili.apk");
    expect(screen.getByText("Broker, charts, mandates, and approvals")).toBeVisible();
  });

  it("lists the search filters from the reference", async () => {
    mocks.home.mockResolvedValue({ items: [], filters: [] });
    render(<KiliHome onOpenSession={vi.fn()} onOpenSettings={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Search" }));
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    for (const label of ["All", "Messages", "Bots", "Group Chats", "Files", "Routines"]) {
      expect(screen.getByRole("button", { name: label })).toBeVisible();
    }
  });
});
