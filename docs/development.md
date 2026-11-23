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
  atlas_mapper.py     Handoffs: agent tools, namespace profile, Collector validation, handoff writers
  Dockerfile
deploy/               the witness compose project: docker-compose.yml, Caddyfile, update.sh, example env files
examples/             a sample Atlas handoff
dev_server.py         local preview server
```

## Local preview

```bash
cp dev-config.example.json dev-config.json   # point opcuaGateway at a running gateway
python3 dev_server.py                        # http://127.0.0.1:8790
```

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
