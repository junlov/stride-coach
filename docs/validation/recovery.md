# Recovery and step compliance proof

This proof uses the actual HTTP server and PostgreSQL, with synthetic Garmin SDK responses.
It requires the disposable database described in [CONTRIBUTING.md](../../CONTRIBUTING.md).
It allocates and removes its own schema and loopback listener. It never connects to Garmin.

```sh
STRIDE_COACH_STORE_GPS=false \
TEST_DATABASE_URL=postgresql://postgres:synthetic-test-password@127.0.0.1:55439/stride_test \
uv run python examples/recovery_demo.py
```

Trimmed output:

```text
sync: synthetic Garmin response stored; readiness=20, HRV=LOW, sleep=40
run detail: stored step score=100; captured laps preserved
proposal: tempo to easy, same duration; preview leaves plan unchanged; missing confirmation rejected
confirmation: saved once; repeated confirmation unchanged; Garmin push remains a preview
proof: real loopback HTTP and PostgreSQL; zero live Garmin calls or writes
```

The mobile TypeScript client also passes `npm run proof` against a real loopback server.
The API demo exercises all 11 read-only MCP tools and rejects write tool names. Automated
screen tests cover recovery display, explicit confirmation, cancellation, stale rejection,
and missing step targets. iOS and Android bundle exports verify compilation. These checks
do not establish live Garmin compatibility, watch delivery, or physical-device appearance.
