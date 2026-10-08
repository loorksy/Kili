# Broker rejection diagnostics and preflight

The previously deployed SDK worker discarded provider rejection fields. The
2026-10-08 rejected pending order cannot be diagnosed retrospectively: its
provider code was never recorded. A client-ID validation failure remains a
hypothesis, not a confirmed broker diagnosis.

New previews generate deterministic 24-character `nb_<10hex>_<10hex>` client
identities. Existing previews, approvals, effects and broker identities are not
rewritten. Create a fresh preview and approve its exact action after deployment;
never resend the previous effect or reuse its consumed approval.

The isolated SDK worker now returns a bounded `ProviderDiagnostic`: exception
kind, string/numeric codes, sanitized message and up to ten validation details.
URLs, bootstrap tokens, JWT-like values and authorization fields are removed.
The gateway additionally redacts both bootstrap and currently configured tokens.
Raw SDK logs, tracebacks and request payloads remain disabled. Operational logs
include effect identity, exception kind, codes and outcome, without message text.
Protected effect results expose `error_kind`, `string_code`, `numeric_code`,
`provider_message`, `details`, `reason_en` and `reason_ar` through existing tools.
No new UI or alternate execution path is introduced.

Returned trade codes and SDK exceptions use the same outcome classifier. Known
rejections become FAILED; timeouts, connection loss, requotes/off-quotes and
unknown codes remain UNCERTAIN. Neither terminal rejection nor uncertain state
replays the effect. Reconciliation still requires the full immutable client
identity, matching instrument, side and volume. A shared prefix or rewritten
SL/TP identity alone does not prove the opening request succeeded.

Broker preflight runs at preview time, before approval, and again at execution:

- Existing volume, direction and decimal precision validation plus tick lattice.
- Real SDK `baseCurrency`, `profitCurrency`, `allowedOrderTypes` aliases;
  older persisted/internal aliases remain accepted.
- Advertised order/protection capabilities, pending price side/distance,
  spread-aware protective stops and broker freeze distance for order edits.
- Advertised expiration capabilities and a timezone-aware expiry at least two
  minutes ahead. Unspecified expiry remains omitted (broker GTC), except delegated
  pending entries retain their mandate-bounded expiry requirement.
- Advertised trading sessions in the broker's clock, derived from the paired
  `time`/`brokerTime` observation. Missing broker clock with advertised sessions
  blocks preflight; it never assumes the gateway's timezone. Day boundaries,
  midnight-ending and overnight sessions are supported.
- Market execution rejects advertised filling sets without FOK/IOC. The SDK
  remains responsible for its supported filling selection; this change does not
  guess or force a pending-order filling mode.

Optional fields absent from older records remain compatible. Broker-provided
constraints are checked when available; these local checks do not substitute for
broker authorization and cannot guarantee execution acceptance.

## Verification and deployment

Deterministic tests cover the reported gold specification and pending request,
capability/session/price/expiry failures, three-part stable IDs, exact-ID
reconciliation, secret redaction, strict IPC frames, exception propagation from
an actual offline worker process through policy/approval/effects, and no replay.
Existing process-death, mandate, risk, approval and isolation tests remain intact.

For an additional offline test using the installed pinned SDK:

```sh
NANOBOT_TEST_METAAPI_SDK_PYTHON=/path/to/internal/metaapi-sdk/bin/python \
  .venv/bin/python -m pytest tests/trading/test_trade_rejections.py -q
```

The SDK test uses a stub transport and makes no network requests or trades.

Deploy using `docs/broker-upgrade-deployment.md`: update/reinstall only the
trading project, then restart only `kili-trading.service` so its private SDK worker
loads the changed source. No SDK version or credentials change is required.
Preserve all runtime data. The separate Nanobot service and other projects must
remain untouched. A future demo order requires fresh exact user approval; it is
not part of automated testing or deployment. Its effect will now identify the
actual provider rejection if one occurs. Historical discarded codes cannot be
recovered.
