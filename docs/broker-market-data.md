# Broker-native market evidence

The `market` tool now uses the selected configured MetaApi account, through
the official SDK connector. `instruments` returns the account's exact symbol
catalog and an account-scoped native canonical identity. Names, punctuation
and broker suffixes are not stripped or translated. Catalog verification
persists only the exact account/symbol identity, without granting financial
authority. Existing user-verified mappings remain valid and conflicting native
identities are rejected.

Quotes carry provider and account identity, bid/ask, provider timestamp and
fetch timestamp. Financial calculations use Decimal. Historical candles come
from the SDK's backward historical-candle API, with pages bounded to 1000
and views bounded to 5000. Dates must contain timezone offsets. Results are
sorted/deduplicated, symbol and OHLC geometry are validated, and a following
bar proves completion; the newest bar remains conservatively partial.
MT4 and MT5 granularities are discovered from account platform metadata.
No strategy, indicator or instrument is selected by default.

The protected candle cache keys include provider and account. Writes reject
data from another account, provider or instrument. Charts and historical
windows carry this scope too. Existing OANDA evidence retains its original
identity; it is not renamed or mixed into a broker series. Legacy chart
contracts expose `needs_account_binding`; broker chart account/source cannot
be changed by ordinary chart edits.

Provider errors and structured-data validation are now provider neutral, so
the trading executor does not depend on OANDA for error handling. A SDK
synchronization wait is followed by another execution/effect ownership check
before outbound financial mutation; tests cover losing ownership during that
wait.

This is the data/binding foundation. Legacy chart loading, streaming and
settings paths still need the subsequent migration changes before the full
OANDA retirement can be deployed.
