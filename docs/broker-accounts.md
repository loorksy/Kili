# Connected broker accounts

`tools.integrations.metaapiAccounts` maps exact MetaApi account IDs to separate
connection profiles (`secretRef`, `accountId`, `region`, `environment`, `name`).
`defaultMetaapiAccount` chooses the default for new conversations. Existing
single `metaapi` configuration is imported deterministically on validation;
that legacy field is retained as the default profile for older clients.
Repeated validation preserves the same profiles and credential references.

Existing Settings lists and edits profiles. Saving another account adds it;
it does not replace the former account, reuse its credential or disable its
approved background missions. Symbol verification accepts an explicit account
ID. Tokens are never returned by the settings API.

The `account` tool supports `list_accounts` and `select_account` as well as an
explicit `account_id` on reads. Conversation selection is a versioned record
in protected `internal/actions.sqlite3`, not workspace files or model metadata.
Selection survives restart and affects only new unbound requests. A selected
account that becomes unavailable produces an explicit error instead of
silently falling back to another account.

Proposals, immutable previews, mandates and effects retain their original
account. Preview, execution, independent risk review, mission controls and
reconciliation resolve that record's account before contacting the provider.
Passing a different account for an existing proposal/mission is rejected.
The existing cron service admits account-filtered mission and reconciliation
sources for every configured account; selecting another chat account does not
move or interrupt that work. No new scheduler is introduced.

Profile selection grants no financial authority. The existing policy,
exact-action user approvals, bounded mandate checks, deterministic risk ledger,
execution ownership and effects/reconciliation remain mandatory.

Frontend profile fields are sent only when the host advertises `accounts`
in integration status, preserving older-host compatibility.
