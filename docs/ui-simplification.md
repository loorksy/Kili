# Kili UI simplification

Audit of the WebUI that shipped at `bb81e2d`, and the decisions applied in this change. Backend capabilities stay. Hidden surfaces are still reachable from chat, settings, or the authenticated API.

## Navigation

| Old surface | Decision | Reason | Where it lives now |
| --- | --- | --- | --- |
| Conversation list | KEEP | Primary workspace | Sidebar, labeled Chats, above secondary tools |
| New topic / search | KEEP | Primary | Top of the sidebar |
| Apps | MOVE | Real integrations, not a daily destination | Sidebar section Tools |
| Skills | MOVE | Power-user capability | Sidebar section Tools, and Settings |
| Automations | KEEP | Primary product area | Sidebar section Tools, still one click |
| Channels | MOVE | Setup, not the daily workspace | Sidebar section Tools |
| Settings | KEEP | Primary | Sidebar footer |
| Trading mandate / approval cards | KEEP | Financial decisions stay in the conversation | Chat cards, now localized |
| Cloud chart | KEEP | Existing chart workspace | Opened from the conversation |
| Computer / browser | KEEP | Existing workbench tools | Contextual tools and Settings capabilities |
| Memory, runtime generations, raw config keys | HIDE | Developer or internal | Not added to primary navigation. Advanced settings still edits supported runtime fields with labels, not environment-variable names |
| Host / remote server switcher | KEEP | Required for paired gateways | Sidebar footer |

Tools stay visible so keyboard shortcuts and existing power-user paths keep working. They are no longer the first block above the conversation list.

## Settings

| Section | Decision | Reason |
| --- | --- | --- |
| Overview, Appearance, Models | KEEP | Daily setup |
| Capabilities (computer, browser, memory, image, voice) | KEEP | Progressive disclosure of real tools |
| System, Advanced, About | KEEP | Advanced owner |
| Apps, Skills, Automations, Channels | KEEP | Opened from Tools or their existing routes |
| Broker accounts | KEEP | Settings integrations. The backend remains the authority for accounts, risk, and execution |
| Raw configuration file editor | HIDE | Not part of the normal product UI |

## Trading card

Approval copy is localized in English and Arabic. Symbols, account ids, and prices render in `dir="ltr"` islands so Arabic layout does not reverse `XAUUSD` or `82,950.34`. Approve and deny still call the existing authenticated approval API. The card cannot submit a broker order by itself.

## Not removed

No backend tool, scheduler, chart feature, or channel was deleted because its control moved down the sidebar. Channel-specific setup strings still fall back to English when an Arabic channel catalog is absent. The shared product catalog is Arabic.
