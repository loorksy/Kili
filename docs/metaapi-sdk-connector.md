# MetaApi SDK connector

Production MetaApi operations use `metaapi-cloud-sdk==29.1.1` for account/domain
discovery and synchronized RPC. The former manually constructed regional REST
host is not used in production. An explicitly injected HTTP transport remains
a deterministic legacy-fixture seam, never a network fallback.

As the gateway service user, using the same configuration-path environment:

```sh
python -m nanobot.trading.sdk_install --config /path/to/data/config.json
```

The installer creates `<config-directory>/internal/metaapi-sdk`, outside the
agent workspace. Requests never install packages automatically. Missing SDK
installation produces an actionable error. The SDK needs Socket.IO 4 / Engine.IO
3; MoChat needs Socket.IO 5. A private provider-connector interpreter isolates
that dependency conflict without adding an agent, scheduler or trading engine.

One connector per account/region/secret-reference is reused by the gateway.
Reads share synchronized RPC; gateway shutdown closes connectors. Tokens cross
private stdin, never arguments. Unrelated environment secrets are excluded.
Validated replies redact reflected credentials; raw SDK/provider exception
text, packet logs and debug logs never cross the connector boundary.

Scoped runtime adapters around the pinned SDK transports preserve public-DNS
pinning, TLS verification and configured operator proxies. Only HTTPS/WSS
MetaApi subdomains are allowed. Installed SDK source is not modified. IPC
exposes fixed operations, no arbitrary URL or SDK method invocation.

Trades use single-instance RPC, zero SDK retries and fixed public mutation
methods. Synchronization precedes a fresh gateway effect/ownership/mandate
check; the bridge also checks the exact current authorized action. Interrupted
requests remain uncertain under the existing reconciliation flow and are never
blindly resent. Calculations stay Decimal; conversion to SDK numeric arguments
rejects values whose decimal representation would change.

The SDK has a service-use license, not MIT. See `THIRD_PARTY_NOTICES.md`.
Deterministic tests cover reuse, account isolation, exposed mutation methods,
precision, token reflection, filtered environment, subprocess death, absence
of retries and unauthorized mutation denial. No test places a real trade.

Live quotes use a shared SDK streaming connection per account while consumers
need it. The pinned public SynchronizationListener emits bounded price frames;
private IPC demultiplexes these independently of RPC responses. Consumers
coalesce newest-per-symbol events and release subscriptions on close. Historical
candles use the SDK historical API, not midpoint synthesis. After synchronization
and again immediately before the queued outbound write, the original execution
scope must still own the STARTED effect. A stale worker cannot send a trade.
