# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Connector not in the list | The `mcp` builtin is allowlist-gated and not allowlisted | An admin adds `mcp` to `connector_plugins_allowlist` |
| `unreachable` on sync | Spawn failed (bad command, missing runtime) or the http endpoint did not answer within the timeout | Use an absolute command; check the service user can run it; raise the timeout for slow boards |
| `protocol` error, "envelope" in the detail | The tool answered, but not in the postings envelope shape | Fix the server (the template repo shows the exact envelope); the app never guesses |
| `invalid` error naming a tool | The source tried a tool outside its allowlist | Add the tool to the per-source allowlist or fix the server's tool name |
| `auth` error | The http endpoint rejected the (absent or wrong) bearer token | Set the token in the source's secret slot — never in config |
| Sync hangs to the timeout | A stuck server process | The call aborts at the configured timeout with a typed error; check the audit row's latency |
| Rows vanish after a server update | The server changed its ids/shape and validation now rejects what it used to accept | Check the sync log's typed errors; re-align the server with the envelope contract |
