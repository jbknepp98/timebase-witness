# Deployment

Witness runs as two containers, defined in [`deploy/docker-compose.yml`](../deploy/docker-compose.yml).

| Service | Image | Role |
| --- | --- | --- |
| `witness` (container `witness-web`) | `caddy:2-alpine` | Serves `site/` on port 8088. Proxies `/api/*` and `/briefs/*` to the gateway; agent streams are not buffered |
| `lookout-gateway` | built from `gateway/` | Connections, live stream, Move to Timebase and handoff files, on port 8090 inside the network |

Keep the gateway's service and host name `lookout-gateway`. Caddy proxies to it, and the URLs inside handoffs point at it.

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
| `OPCUA_SERVERS`, `MQTT_BROKERS` | | Seed connections as JSON. Read only on first start, when there is no `connections.json` yet. See `deploy/gateway.env.example` |

The Move to Timebase variables are listed in [Move to Timebase](move-to-timebase.md#settings).

## Creating the encryption key

```bash
docker run --rm python:3.12-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'" > deploy/lookout-secret/master.key
chmod 600 deploy/lookout-secret/master.key
```

Restart the gateway after adding or replacing the key. Secrets saved with an old key cannot be read with a new one, so enter them again.

## Updating

- **Page only:** copy `site/` to the folder Caddy serves. Caddy sends no-cache headers, so a browser refresh picks up the change.
- **Gateway:**

  ```bash
  docker compose build lookout-gateway
  docker compose up -d lookout-gateway
  ```

  Bump the image tag in the compose file when you release a new version.

  On a host where image pulls fail over SSH (for example a Mac whose keychain is locked), build on another machine and copy the image across:

  ```bash
  docker buildx build --platform linux/arm64 -t lookout-gateway:<ver> --load gateway/
  docker save lookout-gateway:<ver> | ssh <host> docker load
  ```

## Backups

Back up `lookout-data/` and `lookout-secret/master.key` together. Keep `briefs/` if you want handoff history. None of these folders belong in git; `.gitignore` excludes them.
