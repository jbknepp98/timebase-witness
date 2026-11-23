# Gateway API

All paths are served by the gateway on port 8090. Through Caddy they are at `http://<host>:8088`. Nothing returned by the API contains a secret value.

## Connections

| Method | Path | Body or query | Returns |
| --- | --- | --- | --- |
| GET | `/api/connections` | | Connections with `secretsSet` and `secretsStorage` flags, encryption info, and client certificate details |
| POST | `/api/connections` | `{kind, name, enabled, settings, secrets}` | The created connection, or field errors |
| PUT | `/api/connections/{id}` | Same as POST. An empty secret keeps the stored value | The updated connection |
| DELETE | `/api/connections/{id}` | | |
| POST | `/api/connections/test` | Same as POST, plus an optional `id` to reuse stored secrets | Success, or a plain-language error |
| POST | `/api/connections/discover` | `{endpoint}` | The OPC UA server's endpoints, security policies and login types |
| GET | `/api/opcua/client-cert.der` | | The gateway's OPC UA client certificate |
| GET | `/api/opcua/info` | | OPC UA client information |

`kind` is `mqtt` or `opcua`. The secret fields are `password` and `clientKeyPem` for MQTT, and `password` for OPC UA.

## Live stream

Connect a WebSocket to `/api/stream/ws` (`/api/opcua/ws` is an alias). The gateway sends:

| Message | Meaning |
| --- | --- |
| `{"type":"connections","items":[…]}` | The full connection list. Sent on connect and after every change |
| `{"type":"status", …}` | A connection's state, rate and last error |
| `{"type":"removed","id":…}` | A connection was deleted |
| `{"type":"model","server":…}` | An OPC UA address space: nodes, types and units |
| `{"type":"values","server":…,"items":[…]}` | A batch of OPC UA value changes |
| `{"type":"mqtt_snapshot","conn":…,"msgs":[…]}` | Retained and recent MQTT messages, sent on connect |
| `{"type":"mqtt","conn":…,"msgs":[…]}` | New MQTT messages |

## Handoffs

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/agent/info` | Model, effort, whether an API key is configured, and the OPC UA servers available |
| GET | `/api/agent/profile?server=<id>[&path=<object>]` | What the agent's tools see, without calling the model |
| POST | `/api/agent/runs` | Starts a run for `{server, domain?}` and returns the run id. Answers 409 while a run for that server is already in progress |
| GET | `/api/agent/runs/{run}/events` | Server-sent events: progress, tool calls, and the result |
| GET | `/api/agent/latest?server=<id>[&file=<name>]` | The latest (or named) Collector, Connect and Atlas handoffs for a server, with the version list |
| GET | `/briefs/` | Saved handoff files |
| GET | `/briefs/{name}` | One handoff (`.md` or `.json`). Add `?download=1` to download it |

## Health

`GET /healthz` returns `ok`.
