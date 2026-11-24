# Deployment

Witness runs as its own compose project, **witness**, with two containers. Both are defined in [`deploy/docker-compose.yml`](../deploy/docker-compose.yml). It does not need to share a compose project with any broker or Timebase component.

| Service | Image | Role |
| --- | --- | --- |
| `web` (container `witness-web`) | `caddy:2-alpine` | Serves `site/` on port 8088. Proxies `/api/*` and `/briefs/*` to the gateway; agent streams are not buffered |
| `gateway` (container `witness-gateway`, image `witness-gateway:current`) | built from `gateway/` | Connections, live stream, Handoffs and handoff files, on port 8090 inside the network |

The gateway also answers to the network alias `lookout-gateway`, on both networks. The URLs inside handoffs point at that name, so keep the alias.

## Networks

The gateway joins the Timebase stack's Docker network (`timebase-2-0-beta_default` in the example). This lets Gage in Atlas and Collector fetch handoffs, and lets the gateway reach brokers and servers by container name, such as `mosquitto` or `opcua-sim`. Change the network name to match your stack, or remove it if you run Witness on its own.

## Volumes

| Host path (in `deploy/`) | Container path | Contents |
| --- | --- | --- |
| `briefs/` | `/data/briefs` | Saved handoffs |
| `lookout-data/` | `/data/lookout` | `connections.json` and the OPC UA client certificate and key |
| `lookout-secret/` | `/run/lookout` (read-only) | `master.key` |

The gateway runs as uid 1000, so these folders must be writable by it (`chown -R 1000:1000`).

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8090` | Gateway port |
| `LOOKOUT_DATA` | `/data/lookout` | Connection store folder |
| `LOOKOUT_KEY_FILE` | `/run/lookout/master.key` | Fernet key that encrypts secrets |
| `PUBLISH_MS` | `500` | Default OPC UA publishing interval |
| `MAX_NODES` | `5000` | Most OPC UA nodes browsed per server |
| `MQTT_CACHE_MAX` | `20000` | Most retained MQTT topics per broker |
| `MQTT_STATS_MAX` | `100000` | Most MQTT values (topics, JSON leaves, Sparkplug metrics) observed per broker for Handoffs |
| `OPCUA_SERVERS`, `MQTT_BROKERS` | | Seed connections as JSON. Read only on first start, when there is no `connections.json` yet. See `deploy/gateway.env.example` |

The Handoffs variables are listed in [Handoffs](handoffs.md#settings). The Bridge lookup variables (Pulse client) are in [Connections and security](connections-and-security.md#not-for-handoffs).

`tools/probe/` holds a throwaway MQTT broker and fixture publisher, used to check Collector's tag naming against a real Collector. It runs as its own compose project (`witness-probe`) on the Timebase network. See `tools/probe/README.md`.

## Creating the encryption key

```bash
docker run --rm python:3.12-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'" > deploy/lookout-secret/master.key
chmod 600 deploy/lookout-secret/master.key
```

Restart the gateway after adding or replacing the key. Secrets saved with an old key cannot be read with a new one, so enter them again.

## Updating

- **Page only:** copy `site/` to the folder Caddy serves. Caddy sends no-cache headers, so a browser refresh picks up the change.
- **Everything, from git:** run `deploy/update.sh`. It pulls the latest code, which updates the page in place. It rebuilds and restarts the gateway only when `gateway/` changed; add `--rebuild` to force it. Each build is also tagged `witness-gateway:git-<commit>`, and the script prints the command to roll back.
- **Host-specific settings** go in `deploy/update.local.env`, which git ignores. For example, set `DOCKER=/path/to/docker` when `docker` is not on the PATH. On a Mac where image pulls fail over SSH because the keychain is locked, set `DOCKER_CONFIG` to a Docker config folder that has no `credsStore`; public base images don't need credentials.

## Backups

Back up `lookout-data/` and `lookout-secret/master.key` together. Keep `briefs/` if you want handoff history. None of these folders belong in git; `.gitignore` excludes them.
