# Timebase Witness

**See what your industrial data sources are publishing, then move them into Timebase.**

Witness is a browser app for exploring live MQTT brokers and OPC UA servers. It looks and works like the other Timebase 2.0 apps. Each connection opens in its own tab with a namespace browser, current values, quality, trends and a live message feed. **Handoffs** then reads a server's address space and writes two handoffs for Gage: one sets up the Collector instance that logs it, the other builds the Atlas domain that models it.

## Features

- **One list of connections.** Every broker and server appears on one page with live status, message rates and security badges. This is the default view.
- **A tab per connection.**
  - Browse an MQTT topic tree or an OPC UA address space.
  - See current values, data types, quality and short trends.
  - Expand the namespace browser to the full width of the tab with one click.
  - Open the **Live messages** window for the latest 300 messages or value changes.
- **MQTT:** 3.1.1 and 5, over TCP or WebSockets. Supports TLS with a custom CA, client certificates, several topic filters per connection, and `$SYS` statistics.
- **OPC UA:**
  - **Discover** lists a server's security policies and login types.
  - Supports Sign and SignAndEncrypt, certificate pinning, anonymous or user-name login, and limiting a connection to chosen branches.
- **Secrets encrypted at rest.** Passwords and private keys are stored with Fernet encryption, using a key kept apart from the store. The browser only learns whether a secret is set, never its value. If no key is configured, Witness warns before anything is saved as plain text.
- **Handoffs.** A Claude agent with read-only tools profiles an OPC UA namespace and produces:
  - a **Collector handoff**: an OPCUA collector instance, checked against the live namespace, as Markdown plus a downloadable settings JSON;
  - an **Atlas handoff**: a Domain Summary and source bindings that Gage in Atlas builds in Build mode.

  Passwords are never exported.

## How it fits together

```
 Browser ──HTTP/WS──▶ Caddy (:8088) ──▶ Witness gateway (:8090) ──▶ MQTT brokers
   site/                serves site/      gateway/                   OPC UA servers
                        proxies /api,     connections, live stream,  Anthropic API (Handoffs)
                        /briefs           agent, handoff files
                                                │
                     Gage in Collector / Atlas ◀┘ fetch handoffs over the Timebase network
```

The page never talks to a broker or server. The gateway owns every connection and streams to the page over one WebSocket.

## Quick start

You need Docker with Compose, and a Timebase 2.0 stack if you want to use Handoffs.

```bash
git clone https://github.com/jbknepp98/timebase-witness.git
cd timebase-witness/deploy
cp gateway.env.example gateway.env
cp agent.env.example agent.env        # add ANTHROPIC_API_KEY to use Handoffs
mkdir -p briefs lookout-data lookout-secret
docker run --rm python:3.12-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'" > lookout-secret/master.key
chmod 600 lookout-secret/master.key
sudo chown -R 1000:1000 briefs lookout-data lookout-secret
docker compose up -d --build
```

Witness runs as its own compose project, `witness`, with containers `witness-web` and `witness-gateway`. To update it later, run `deploy/update.sh`.

Open `http://<host>:8088`, choose **Add connection**, and test it before saving. If you are not running Timebase, remove the `timebase` network from `deploy/docker-compose.yml` first.

## Documentation

| Guide | What it covers |
| --- | --- |
| [Using Witness](docs/using-witness.md) | Connections list, connection tabs, namespace browser, live messages, links and keyboard |
| [Connections and security](docs/connections-and-security.md) | MQTT and OPC UA settings, TLS and certificates, how secrets are stored |
| [Handoffs](docs/handoffs.md) | What the agent does, the two handoffs, running them in Gage, cost |
| [Deployment](docs/deployment.md) | Compose, Caddy, volumes, environment variables, upgrades, backups |
| [Gateway API](docs/api.md) | REST endpoints and WebSocket messages |
| [Development](docs/development.md) | Code layout, local preview, building the gateway image, design tokens |

There is an example Atlas handoff from the DemoPlant simulator in [examples/demo-plant-gage-brief.md](examples/demo-plant-gage-brief.md).

## Status and limits

- Witness has **no login yet**. Anyone who can open the page can add, edit or delete connections, though never read their secrets. Keep it on a trusted network.
- The Handoffs page supports OPC UA. MQTT namespaces are not planned yet.
- Witness was called Lookout until November 2026. Some internal names still use the old spelling because handoffs, certificates and volumes depend on them. These are the `lookout-gateway` network alias, the `LOOKOUT_*` variables, the `lookout-*` folders, and the OPC UA application URI `urn:flow-software:lookout-gateway`.
