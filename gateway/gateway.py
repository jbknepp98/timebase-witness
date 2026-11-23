"""Witness gateway: owns Witness's connections to MQTT brokers and OPC UA servers.

Browsers never talk to a broker or server directly. The gateway connects (with TLS, certificates and
credentials as configured), subscribes, and streams everything to the page over one WebSocket.
Connections are managed through the REST API below and stored by connections.py, which encrypts
passwords and private keys at rest. The gateway also runs Handoffs (atlas_mapper.py) and serves
the saved Gage handoff briefs.

REST
  GET    /api/connections                  list (no secret values) + storage/encryption info + client certificate
  POST   /api/connections                  create         {kind, name, enabled, settings, secrets}
  PUT    /api/connections/{id}             update (an empty secret keeps the stored one)
  DELETE /api/connections/{id}             remove
  POST   /api/connections/test             try settings without saving (optional id reuses stored secrets)
  POST   /api/connections/discover         OPC UA endpoints and their security for {endpoint}
  GET    /api/opcua/client-cert.der        the gateway's OPC UA client certificate, for servers to trust
WebSocket /api/stream/ws (also /api/opcua/ws)
  {"type": "connections", "items"}  {"type": "status", ...}  {"type": "removed", "id"}
  OPC UA: {"type": "model", "server", ...}  {"type": "values", "server", "items"}
  MQTT:   {"type": "mqtt_snapshot", "conn", "msgs"}  {"type": "mqtt", "conn", "msgs"}
"""
import asyncio
import datetime as dt
import json
import logging
import os
import re
import uuid

from aiohttp import web, WSMsgType

import atlas_mapper
import connections as cx

log = logging.getLogger("lookout-gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("asyncua").setLevel(logging.WARNING)

PORT = int(os.environ.get("PORT", "8090"))


class Hub:
    """Fan-out to browser WebSockets."""

    def __init__(self):
        self.clients = set()

    async def broadcast(self, msg):
        if not self.clients:
            return
        data = json.dumps(msg, default=str)
        for ws in list(self.clients):
            try:
                await ws.send_str(data)
            except Exception:  # noqa: BLE001
                self.clients.discard(ws)


HUB = Hub()


class Manager:
    def __init__(self):
        self.store = cx.Store()
        self.conns = {}
        self.lock = asyncio.Lock()

    def make(self, rec):
        return (cx.MqttConn if rec["kind"] == "mqtt" else cx.OpcUaConn)(rec, HUB)

    async def start(self):
        await cx.CLIENT_CERT.ensure()
        if not self.store.load() and not self.store.path.exists():
            self.store.records = cx.seed_from_env()
            self.store.save()
            log.info("created %s with %d connections from the environment", self.store.path, len(self.store.records))
        for rec in self.store.records:
            c = self.make(rec)
            self.conns[rec["id"]] = c
            c.start()

    def opcua(self, cid):
        c = self.conns.get(cid or "")
        return c if c and c.kind == "opcua" else None

    def statuses(self):
        return [c.status() for c in self.conns.values()]

    async def broadcast_list(self):
        await HUB.broadcast({"type": "connections", "items": self.statuses()})

    async def upsert(self, rec):
        async with self.lock:
            old = self.conns.get(rec["id"])
            if old:
                await old.stop()
            self.store.records = [r for r in self.store.records if r["id"] != rec["id"]] + [rec]
            self.store.save()
            c = self.make(rec)
            self.conns[rec["id"]] = c
            c.start()
        if old:
            await HUB.broadcast({"type": "removed", "id": rec["id"], "replaced": True})
        await self.broadcast_list()
        return c

    async def remove(self, cid):
        async with self.lock:
            c = self.conns.pop(cid, None)
            if c:
                await c.stop()
            self.store.records = [r for r in self.store.records if r["id"] != cid]
            self.store.save()
        await HUB.broadcast({"type": "removed", "id": cid})
        await self.broadcast_list()


MANAGER = Manager()


# ---------------------------------------------------------------------- WebSocket
async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=0)
    await ws.prepare(request)
    HUB.clients.add(ws)
    await ws.send_str(json.dumps({"type": "connections", "items": MANAGER.statuses()}, default=str))
    for c in list(MANAGER.conns.values()):
        await ws.send_str(json.dumps(c.snapshot(), default=str))
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT and msg.data == "ping":
                await ws.send_str(json.dumps({"type": "connections", "items": MANAGER.statuses()}, default=str))
    finally:
        HUB.clients.discard(ws)
    return ws


# ---------------------------------------------------------------------- connection API
def meta():
    return {"storage": cx.vault().info(), "clientCert": cx.CLIENT_CERT.info(),
            "policies": list(cx.POLICIES), "modes": ["None", *cx.MODES]}


def bad(errors, status=400):
    return web.json_response({"errors": errors}, status=status)


async def body_of(request):
    try:
        return await request.json()
    except Exception:  # noqa: BLE001
        return {}


async def conn_list(_request):
    items = []
    for rec in MANAGER.store.records:
        c = MANAGER.conns.get(rec["id"])
        items.append({**cx.public(rec), "status": c.status() if c else None})
    return web.json_response({"items": items, "meta": meta()}, dumps=lambda o: json.dumps(o, default=str))


async def conn_create(request):
    body = await body_of(request)
    kind = body.get("kind")
    rec, errors = cx.normalize(kind, body)
    if errors:
        return bad(errors)
    if any(r["name"].lower() == rec["name"].lower() for r in MANAGER.store.records):
        return bad({"name": "Another connection already has this name."})
    base = cx.slug(rec["name"]).lower()
    cid, n = base, 2
    while MANAGER.store.get(cid):
        cid, n = f"{base}-{n}", n + 1
    rec["id"] = cid
    await MANAGER.upsert(rec)
    log.info("connection %s (%s) created", cid, kind)
    return web.json_response(cx.public(rec), status=201)


async def conn_update(request):
    cid = request.match_info["id"]
    existing = MANAGER.store.get(cid)
    if not existing:
        return bad({"id": "No such connection."}, 404)
    body = await body_of(request)
    rec, errors = cx.normalize(existing["kind"], body, existing)
    if errors:
        return bad(errors)
    if any(r["id"] != cid and r["name"].lower() == rec["name"].lower() for r in MANAGER.store.records):
        return bad({"name": "Another connection already has this name."})
    await MANAGER.upsert(rec)
    log.info("connection %s updated", cid)
    return web.json_response(cx.public(rec))


async def conn_delete(request):
    cid = request.match_info["id"]
    if not MANAGER.store.get(cid):
        return bad({"id": "No such connection."}, 404)
    await MANAGER.remove(cid)
    log.info("connection %s removed", cid)
    return web.json_response({"removed": cid})


async def conn_test(request):
    body = await body_of(request)
    existing = MANAGER.store.get(body.get("id") or "")
    kind = existing["kind"] if existing else body.get("kind")
    rec, errors = cx.normalize(kind, {**body, "name": body.get("name") or "test"}, existing)
    if errors:
        return bad(errors)
    try:
        result = await asyncio.wait_for(cx.test_connection(rec), 25)
    except asyncio.TimeoutError:
        result = {"ok": False, "message": "No answer within 25 seconds. Check the address, port and firewall."}
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "message": explain(e)}
    return web.json_response(result)


def explain(e):
    text = str(e) or type(e).__name__
    low = text.lower()
    if "certificate verify failed" in low:
        return f"The broker's certificate was not trusted ({text}). Add the CA certificate that signed it, or turn off certificate verification for a lab broker."
    if "not authorized" in low or "bad user name or password" in low or "badusernotauthorized" in low or "baduseraccessdenied" in low or "badidentitytokenrejected" in low:
        return f"The server rejected the user name or password ({text})."
    if "badsecuritychecksfailed" in low or "badcertificateuntrusted" in low:
        return f"The server did not trust Witness's client certificate ({text}). Add the certificate below to the server's trusted clients."
    if "connection refused" in low or "errno 111" in low or "connect call failed" in low:
        return f"Nothing is listening at that address and port ({text})."
    if "name or service not known" in low or "nodename nor servname" in low or "temporary failure in name resolution" in low:
        return f"The host name could not be resolved ({text})."
    return text


async def conn_discover(request):
    body = await body_of(request)
    ep = str(body.get("endpoint") or "").strip()
    if not ep.startswith("opc.tcp://"):
        return bad({"endpoint": "The endpoint must start with opc.tcp://"})
    try:
        return web.json_response({"endpoints": await cx.discover(ep)})
    except Exception as e:  # noqa: BLE001
        return web.json_response({"endpoints": [], "error": explain(e)})


async def client_cert(_request):
    return web.Response(body=cx.CLIENT_CERT.der, content_type="application/pkix-cert",
                        headers={"Content-Disposition": 'attachment; filename="lookout-client-cert.der"'})


RUNS = {}       # run id -> atlas_mapper.MapRun

# ---------------------------------------------------------------------- brief artifacts
# Every finished brief is saved as a versioned Markdown file that Gage (inside the Atlas
# container, on the same Docker network) can fetch by URL. demo-plant-v3.md never changes;
# demo-plant.md is always the newest version of that domain.
BRIEF_DIR = os.environ.get("BRIEF_DIR", "/data/briefs")
INTERNAL_URL = os.environ.get("LOOKOUT_INTERNAL_URL", "http://lookout-gateway:8090")
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*(-v\d+)?\.(md|json)$")


def brief_index():
    try:
        with open(os.path.join(BRIEF_DIR, "index.json")) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def write_atomic(name, text):
    tmp = os.path.join(BRIEF_DIR, name + ".tmp")
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, os.path.join(BRIEF_DIR, name))


def save_brief(run):
    os.makedirs(BRIEF_DIR, exist_ok=True)
    index = brief_index()
    version = 1 + max((e["version"] for e in index if e["domain"] == run.domain), default=0)
    st = run.server.status()
    created = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    name = f"{run.domain}-v{version}.md"
    entry = {"domain": run.domain, "version": version, "file": name, "latest": f"{run.domain}.md",
             "url": f"{INTERNAL_URL}/briefs/{name}", "latestUrl": f"{INTERNAL_URL}/briefs/{run.domain}.md",
             "server": st["id"], "serverName": st["name"], "endpoint": st["endpoint"], "connector": st.get("connector"),
             "model": atlas_mapper.MODEL, "createdAt": created}
    header = "\n".join([
        "---",
        "lookout_brief: 1",
        f"domain: {run.domain}",
        f"version: {version}",
        f"source: {st['name']} ({st['endpoint']})",
        f"bindings: Connect Historian connector for dataset {run.collector['historian']['dataset'] if run.collector else 'none'}",
        f"generated: {created}",
        f"model: {atlas_mapper.MODEL}",
        f"url: {entry['url']}",
        "---",
        "",
    ])
    text = header + run.brief.rstrip() + "\n"
    for fn in (name, f"{run.domain}.md"):
        write_atomic(fn, text)
    if run.collector:
        inst = run.collector
        base = f"{run.domain}-collector"
        md_name, json_name = f"{base}-v{version}.md", f"{base}-v{version}.json"
        json_url = f"{INTERNAL_URL}/briefs/{json_name}"
        settings_text = json.dumps({"Settings": inst["Settings"]}, indent=2) + "\n"
        c_header = "\n".join(["---", "lookout_collector_handoff: 1", f"instance: {inst['name']}", f"dataset: {inst['historian']['dataset']}",
                               f"version: {version}", f"source: {st['name']} ({st['endpoint']})", f"generated: {created}",
                               f"url: {INTERNAL_URL}/briefs/{md_name}", "---", ""])
        c_text = c_header + atlas_mapper.collector_brief(run.server, inst, json_url).rstrip() + "\n"
        for fn in (md_name, f"{base}.md"):
            write_atomic(fn, c_text)
        for fn in (json_name, f"{base}.json"):
            write_atomic(fn, settings_text)
        entry["collector"] = {"file": md_name, "url": f"{INTERNAL_URL}/briefs/{md_name}", "json": json_name, "jsonUrl": json_url,
                              "name": inst["name"], "dataset": inst["historian"]["dataset"], "variablesLogged": inst["variablesLogged"]}
    if run.connect:
        plan = run.connect
        base = f"{run.domain}-connect"
        md_name, json_name = f"{base}-v{version}.md", f"{base}-v{version}.json"
        json_url = f"{INTERNAL_URL}/briefs/{json_name}"
        n_header = "\n".join(["---", "lookout_connect_handoff: 1", f"connector: {plan['name']}", f"dataset: {plan['dataset']}",
                               f"version: {version}", f"source: {st['name']} ({st['endpoint']})", f"generated: {created}",
                               f"url: {INTERNAL_URL}/briefs/{md_name}", "---", ""])
        n_text = n_header + atlas_mapper.connect_brief(run.server, plan, json_url).rstrip() + "\n"
        for fn in (md_name, f"{base}.md"):
            write_atomic(fn, n_text)
        for fn in (json_name, f"{base}.json"):
            write_atomic(fn, json.dumps({"Settings": plan["Settings"]}, indent=2) + "\n")
        entry["connect"] = {"file": md_name, "url": f"{INTERNAL_URL}/briefs/{md_name}", "json": json_name, "jsonUrl": json_url,
                            "name": plan["name"], "dataset": plan["dataset"], "tagCount": plan["tagCount"]}
    index.append(entry)
    tmp = os.path.join(BRIEF_DIR, "index.json.tmp")
    with open(tmp, "w") as f:
        json.dump(index, f, indent=2)
    os.replace(tmp, os.path.join(BRIEF_DIR, "index.json"))
    run.brief = text
    log.info("saved brief %s", name)
    return entry


async def briefs_list(_request):
    return web.json_response(sorted(brief_index(), key=lambda e: e["createdAt"], reverse=True))


async def briefs_file(request):
    name = request.match_info["name"]
    if not SAFE_NAME.match(name):
        return web.Response(status=404, text="Not found")
    path = os.path.join(BRIEF_DIR, name)
    if not os.path.isfile(path):
        return web.Response(status=404, text="Not found")
    disposition = "attachment" if request.query.get("download") else "inline"
    ctype = "application/json" if name.endswith(".json") else "text/markdown"
    with open(path) as f:
        return web.Response(text=f.read(), content_type=ctype, charset="utf-8",
                            headers={"Cache-Control": "no-cache", "Content-Disposition": f'{disposition}; filename="{name}"'})


async def agent_start(request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    server = MANAGER.opcua(body.get("server"))
    if not server:
        return web.json_response({"error": "Unknown OPC UA server."}, status=404)
    domain = re.sub(r"[^a-z0-9-]+", "-", str(body.get("domain") or server.id).lower()).strip("-") or "lookout-domain"
    if any(not r.done and r.server is server for r in RUNS.values()):
        return web.json_response({"error": "A mapping run for this server is already in progress."}, status=409)
    run_id = uuid.uuid4().hex[:12]
    run = atlas_mapper.MapRun(server, domain, on_brief=save_brief)
    RUNS[run_id] = run
    asyncio.get_event_loop().create_task(run.run())
    return web.json_response({"run": run_id, "domain": domain})


async def agent_events(request):
    run = RUNS.get(request.match_info["run"])
    if not run:
        return web.json_response({"error": "Unknown run."}, status=404)
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    await resp.prepare(request)
    sent = 0
    while True:
        async with run.cond:
            if sent >= len(run.events) and not run.done:
                try:
                    await asyncio.wait_for(run.cond.wait(), timeout=15)
                except asyncio.TimeoutError:
                    pass
            batch = run.events[sent:]
        if not batch and sent >= len(run.events):
            if run.done:
                break
            await resp.write(b": keep-alive\n\n")
            continue
        for ev in batch:
            await resp.write(f"data: {json.dumps(ev, default=str)}\n\n".encode())
        sent += len(batch)
    await resp.write(b"event: end\ndata: {}\n\n")
    return resp


async def agent_latest(request):
    server = request.query.get("server", "")
    entries = [e for e in brief_index() if e["server"] == server]
    if not entries:
        return web.json_response({"brief": None, "versions": []})
    entries.sort(key=lambda e: e["createdAt"], reverse=True)
    want = request.query.get("file")
    entry = next((e for e in entries if e["file"] == want), entries[0])
    def read(fn):
        try:
            with open(os.path.join(BRIEF_DIR, fn)) as f:
                return f.read()
        except (FileNotFoundError, TypeError):
            return None
    text = read(entry["file"])
    collector = read((entry.get("collector") or {}).get("file"))
    connect = read((entry.get("connect") or {}).get("file"))
    return web.json_response({"brief": text, "collector": collector, "connect": connect, "artifact": entry, "domain": entry["domain"], "versions": entries})


async def agent_profile(request):
    """Read-only: what the agent's tools return, without calling the model."""
    server = MANAGER.opcua(request.query.get("server"))
    if not server:
        return web.json_response({"error": "Unknown OPC UA server."}, status=404)
    view = atlas_mapper.NamespaceView(server)
    path = request.query.get("path")
    return web.json_response(view.inspect(path) if path else view.profile(), dumps=lambda o: json.dumps(o, default=str))


async def agent_info(_request):
    return web.json_response({"model": atlas_mapper.MODEL, "effort": atlas_mapper.EFFORT,
                              "keyConfigured": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))})



async def info_handler(_request):
    return web.json_response({"servers": [c.status() for c in MANAGER.conns.values() if c.kind == "opcua"]})


async def on_startup(app):
    await MANAGER.start()


async def on_cleanup(app):
    for c in list(MANAGER.conns.values()):
        await c.stop()


def main():
    app = web.Application(client_max_size=4 * 1024 * 1024)
    for path in ("/api/opcua/ws", "/api/stream/ws"):
        app.router.add_get(path, ws_handler)
    app.router.add_get("/api/opcua/info", info_handler)
    app.router.add_get("/api/opcua/client-cert.der", client_cert)
    app.router.add_get("/api/connections", conn_list)
    app.router.add_post("/api/connections", conn_create)
    app.router.add_post("/api/connections/test", conn_test)
    app.router.add_post("/api/connections/discover", conn_discover)
    app.router.add_put("/api/connections/{id}", conn_update)
    app.router.add_delete("/api/connections/{id}", conn_delete)
    app.router.add_post("/api/agent/runs", agent_start)
    app.router.add_get("/api/agent/runs/{run}/events", agent_events)
    app.router.add_get("/api/agent/latest", agent_latest)
    app.router.add_get("/api/agent/info", agent_info)
    app.router.add_get("/api/agent/profile", agent_profile)
    app.router.add_get("/briefs/", briefs_list)
    app.router.add_get("/briefs/{name}", briefs_file)
    app.router.add_get("/healthz", lambda r: web.Response(text="ok"))
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    log.info("Witness gateway listening on :%d", PORT)
    web.run_app(app, port=PORT, print=None)


if __name__ == "__main__":
    main()
