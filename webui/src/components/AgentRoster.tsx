import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useClient } from "@/providers/ClientProvider";
import {
  changeKiliGroupMember,
  createKiliAgent,
  createKiliGroup,
  fetchAgentRoster,
  type KiliAgentSummary,
  type KiliGroupSummary,
} from "@/lib/api";

const copy = {
  en: {
    title: "Agents",
    create: "Create agent",
    name: "Agent name",
    instructions: "Instructions",
    save: "Save agent",
    group: "Create group",
    groupName: "Group name",
    open: "Open",
    remove: "Remove",
    empty: "No agents yet.",
  },
  ar: {
    title: "الوكلاء",
    create: "إنشاء وكيل",
    name: "اسم الوكيل",
    instructions: "التعليمات",
    save: "حفظ الوكيل",
    group: "إنشاء مجموعة",
    groupName: "اسم المجموعة",
    open: "فتح",
    remove: "إزالة",
    empty: "لا يوجد وكلاء بعد.",
  },
} as const;

export function AgentRoster({ onOpen }: { onOpen: (sessionKey: string) => void }) {
  const { i18n } = useTranslation();
  const { token, client } = useClient();
  const text = i18n.language === "ar" ? copy.ar : copy.en;
  const [agents, setAgents] = useState<KiliAgentSummary[]>([]);
  const [groups, setGroups] = useState<KiliGroupSummary[]>([]);
  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");
  const [groupName, setGroupName] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  async function load() {
    const roster = await fetchAgentRoster(token);
    setAgents(roster.agents);
    setGroups(roster.groups);
  }
  useEffect(() => { void load().catch(() => undefined); }, [token]);

  async function saveAgent() {
    if (!name.trim() || !instructions.trim()) return;
    setBusy(true);
    try {
      const agent = await createKiliAgent(client, name.trim(), instructions.trim());
      setName("");
      setInstructions("");
      await load();
      onOpen(agent.session_key);
    } finally { setBusy(false); }
  }
  async function saveGroup() {
    if (!groupName.trim() || selected.length < 2) return;
    setBusy(true);
    try {
      const group = await createKiliGroup(client, groupName.trim(), selected);
      setGroupName("");
      setSelected([]);
      await load();
      onOpen(group.session_key);
    } finally { setBusy(false); }
  }

  return <section className="border-t border-sidebar-border px-3 py-3 text-sm" aria-label={text.title}>
    <p className="px-1 pb-2 text-[11px] font-medium text-sidebar-muted-foreground">{text.title}</p>
    {agents.length === 0 ? <p className="px-1 text-xs text-sidebar-muted-foreground">{text.empty}</p> : null}
    <ul className="space-y-1">
      {agents.map(agent => (
        <li key={agent.id}>
          <button type="button" className="w-full rounded-lg px-2 py-1.5 text-start hover:bg-sidebar-accent" onClick={() => onOpen(agent.session_key)}>
            {agent.name}
          </button>
        </li>
      ))}
    </ul>
    <div className="mt-2 space-y-2">
      <input aria-label={text.name} value={name} onChange={event => setName(event.target.value)} placeholder={text.name} className="w-full rounded-lg border border-sidebar-border bg-transparent px-2 py-1.5" />
      <textarea aria-label={text.instructions} value={instructions} onChange={event => setInstructions(event.target.value)} placeholder={text.instructions} className="h-16 w-full rounded-lg border border-sidebar-border bg-transparent px-2 py-1.5" />
      <button type="button" disabled={busy} className="min-h-11 rounded-lg bg-primary px-3 text-primary-foreground" onClick={() => void saveAgent()}>{text.save}</button>
    </div>
    <div className="mt-3 space-y-2">
      {agents.map(agent => (
        <label key={agent.id} className="flex items-center gap-2 px-1">
          <input type="checkbox" checked={selected.includes(agent.id)} onChange={() => setSelected(current => current.includes(agent.id) ? current.filter(id => id !== agent.id) : [...current, agent.id])} />
          <span>{agent.name}</span>
        </label>
      ))}
      <input aria-label={text.groupName} value={groupName} onChange={event => setGroupName(event.target.value)} placeholder={text.groupName} className="w-full rounded-lg border border-sidebar-border bg-transparent px-2 py-1.5" />
      <button type="button" disabled={busy || selected.length < 2} className="min-h-11 rounded-lg border border-sidebar-border px-3" onClick={() => void saveGroup()}>{text.group}</button>
    </div>
    {groups.map(group => (
      <div key={group.id} className="mt-3 rounded-lg border border-sidebar-border p-2">
        <button type="button" className="font-medium" onClick={() => onOpen(group.session_key)}>{text.open} {group.name}</button>
        <ul className="mt-1 space-y-1">
          {group.members.map(member => (
            <li key={member.id} className="flex items-center justify-between gap-2">
              <span>{member.name}</span>
              <button type="button" className="min-h-11 text-xs" onClick={() => void changeKiliGroupMember(client, group.id, member.id, "remove").then(load)}>
                {text.remove}
              </button>
            </li>
          ))}
        </ul>
      </div>
    ))}
  </section>;
}
