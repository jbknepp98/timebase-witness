# Development

## Layout

```
site/                 the web page: plain HTML, CSS and JavaScript, no build step
  index.html          shell: sidebar, tab strip, page; applies the stored theme before first paint
  app.js              views, routing, connection tabs, namespace tree, live feed, dialogs, Handoffs
  app.css             Timebase 2.0 shell styles (--tb-* tokens)
  config.json         {"title": "Witness"}
  brand/              Timebase icon
gateway/              Python 3.12 (aiohttp, asyncua, aiomqtt, anthropic)
  gateway.py          HTTP and WebSocket server, agent runs, handoff files
  connections.py      connection store, secret encryption, MQTT and OPC UA sessions
  atlas_mapper.py     Handoffs: agent prompt and tools, runs, the Atlas brief preface
  source_model.py     the source model (objects and signals) the agent's tools read
  adapters/           build the source model from an OPC UA server, MQTT topics and Sparkplug B
  payload_shapes.py   MQTT payload shapes and topic groups
  sparkplug.py        Sparkplug B decoding, aliases and births per Edge Node
  hints.py            type and unit hints (OPC UA types, Sparkplug templates, metadata topics, JSON keys)
  collector_naming.py predicts the tags a Collector subscription writes
  collector_plan.py   checks Collector plans and writes their settings
  handoff_text.py     the Collector and Connect handoffs
  bridge_lookup.py    which topics Timebase Bridge publishes
  tests/              unit tests (standard library only)
  Dockerfile
deploy/               the witness compose project: docker-compose.yml, Caddyfile, update.sh, example env files
examples/             a sample Atlas handoff
tools/probe/          probe harness: a test broker and fixtures, and the tags a real Collector wrote for them
dev_server.py         local preview server
```

## Local preview

```bash
cp dev-config.example.json dev-config.json   # point opcuaGateway at a running gateway
python3 dev_server.py                        # http://127.0.0.1:8790
```

## Tests

```bash
python3 -m unittest discover -s gateway/tests
```

The tests use only the standard library. They run against `tools/probe/fixtures.json` (one recorded round of every probe message) and `tools/probe/expected-tags.json` (what a real Collector wrote for them). When a Collector release changes its naming, record new fixtures and expected tags with the probe harness (`tools/probe/README.md`), then fix `collector_naming.py` until the tests pass.

## How the local preview works

`dev_server.py` serves `site/` and replaces `config.json` with `dev-config.json`. It forwards `/api/` requests to the gateway host in `opcuaGateway`, so connections and Handoffs work locally without CORS; keep `"apiBase": ""` in `dev-config.json` for that. The live stream connects to the gateway directly over WebSocket.

## Gateway

```bash
docker build -t witness-gateway:dev gateway/
```

The dependencies are pinned in the Dockerfile. The gateway logs to stdout; follow it with `docker logs -f witness-gateway`.

## Look and feel

`site/app.css` reproduces the Timebase 2.0 app shell, measured from the Historian UI:

- `--tb-*` colour tokens, with light and dark themes;
- Poppins for text and JetBrains Mono for values;
- the sidebar lockup, the tab strip and Datasets-style lists;
- Lucide-style 2px line icons.

Keep it in step with the Timebase design system. Choices in forms use dropdowns rather than segmented buttons.

## Conventions

- Secrets never leave the gateway. Never return a secret from the API or write one into a handoff.
- Keep the `lookout` internal names (see the README) unless you also migrate the volumes, the handoff URLs and the trusted client certificates.
