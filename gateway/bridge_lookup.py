"""Which MQTT topics Timebase Bridge publishes, so Handoffs never plans them.

Bridge publishes Atlas data back to MQTT. Logging those topics again with Collector would loop
Timebase's own output into Historian, so every broker connection leaves them out of Handoffs.

When the gateway has a Pulse client (env below), it asks Bridge every LOOKUP_SECONDS through Bridge's
MCP endpoint, which accepts Pulse bearer tokens: ListInstances, then GetInstanceSettings for each MQTT
instance. Each subscription's Topic template is cut at its first placeholder, so
`timebase/bluebird-bev/[type.@name]/[instance.@name]` becomes `timebase/bluebird-bev/#`. Those filters
apply to the broker connections whose host matches the Bridge instance's Host.

Without a Pulse client, or while the lookup fails, FALLBACK (`timebase/#`) applies to every broker.

Env: BRIDGE_URL (https://bridge:4572), PULSE_URL (https://pulse:4542), WITNESS_PULSE_CLIENT_ID,
WITNESS_PULSE_CLIENT_SECRET, PULSE_CA_FILE (PEM of the Pulse root CA, to verify both).
"""
import asyncio
import json
import logging
import os
import re
import ssl
import time

log = logging.getLogger("lookout-gateway")

BRIDGE_URL = os.environ.get("BRIDGE_URL", "https://bridge:4572").rstrip("/")
PULSE_URL = os.environ.get("PULSE_URL", "https://pulse:4542").rstrip("/")
CLIENT_ID = os.environ.get("WITNESS_PULSE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("WITNESS_PULSE_CLIENT_SECRET", "")
CA_FILE = os.environ.get("PULSE_CA_FILE", "")
LOOKUP_SECONDS = int(os.environ.get("BRIDGE_LOOKUP_SECONDS", "600"))
FALLBACK = ["timebase/#"]

STATE = {"configured": bool(CLIENT_ID and CLIENT_SECRET), "byHost": {}, "error": None, "checkedAt": None}


def topic_prefix_filter(template):
    """Bridge topic template -> the filter that covers everything it can publish."""
    cut = template.find("[")
    if cut < 0:
        return template
    head = template[:cut]
    head = head[:head.rfind("/") + 1] if "/" in head else ""
    return (head + "#") if head else "#"


def bridge_excludes(settings):
    """{"filters", "source": "bridge"|"fallback", "error"?} for one broker connection's settings."""
    if STATE["configured"] and STATE["checkedAt"] and not STATE["error"]:
        host = str(settings.get("host") or "").lower()
        return {"filters": sorted(STATE["byHost"].get(host, [])), "source": "bridge", "checkedAt": STATE["checkedAt"]}
    out = {"filters": list(FALLBACK), "source": "fallback"}
    if not STATE["configured"]:
        out["reason"] = "The gateway has no Pulse client for reading Bridge (WITNESS_PULSE_CLIENT_ID / _SECRET)."
    elif STATE["error"]:
        out["reason"] = f"Bridge could not be read: {STATE['error']}"
    else:
        out["reason"] = "Bridge has not been read yet."
    return out


def effective_excludes(settings):
    """All filters Handoffs leaves out for a broker, with where each came from."""
    own = list(settings.get("handoffExclude", ["$SYS/#"]))
    br = bridge_excludes(settings)
    return {"filters": own + [f for f in br["filters"] if f not in own], "connection": own, "bridge": br}


# ---------------------------------------------------------------------- lookup
def _ssl():
    ctx = ssl.create_default_context()
    if CA_FILE:
        ctx.load_verify_locations(CA_FILE)
    return ctx


async def _token(session):
    async with session.post(f"{PULSE_URL}/auth/token", data={"grant_type": "client_credentials", "client_id": CLIENT_ID,
                                                             "client_secret": CLIENT_SECRET}, ssl=_ssl()) as r:
        body = await r.json(content_type=None)
        if r.status != 200 or "access_token" not in body:
            raise RuntimeError(f"Pulse refused the client: {body.get('error_description') or body.get('error') or r.status}")
        return body["access_token"]


def _rpc_result(text, content_type, rid):
    """A JSON-RPC response, sent as JSON or as server-sent events."""
    if "text/event-stream" in content_type:
        for line in text.splitlines():
            if line.startswith("data:"):
                msg = json.loads(line[5:].strip())
                if msg.get("id") == rid:
                    return msg
        raise RuntimeError("no response in the event stream")
    return json.loads(text)


class Mcp:
    def __init__(self, session, token):
        self.s, self.token, self.sid, self.n = session, token, None, 0

    async def call(self, method, params=None, notify=False):
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json, text/event-stream",
                   "Content-Type": "application/json"}
        if self.sid:
            headers["Mcp-Session-Id"] = self.sid
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self.n += 1
            msg["id"] = self.n
        async with self.s.post(f"{BRIDGE_URL}/mcp", json=msg, headers=headers, ssl=_ssl()) as r:
            self.sid = r.headers.get("Mcp-Session-Id", self.sid)
            if r.status == 401:
                raise RuntimeError("Bridge refused the Pulse token (401). Give the Witness client access to Bridge in Pulse.")
            if notify:
                return None
            text = await r.text()
            if r.status >= 400:
                raise RuntimeError(f"Bridge MCP {method} answered {r.status}: {text[:200]}")
            res = _rpc_result(text, r.headers.get("Content-Type", ""), msg["id"])
            if "error" in res:
                raise RuntimeError(f"Bridge MCP {method}: {res['error'].get('message')}")
            return res["result"]

    async def tool_text(self, name, args=None):
        res = await self.call("tools/call", {"name": name, "arguments": args or {}})
        if res.get("isError"):
            raise RuntimeError(f"Bridge tool {name} failed: {res['content'][0].get('text', '')[:200]}")
        return "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")


def parse_instances(text):
    """Bridge ListInstances table -> [(id, type)]."""
    return re.findall(r"^(brg_\w+)\s+(\S+)", text, re.M)


def parse_settings(text):
    m = re.search(r"```json\s*(\{.*\})\s*```", text, re.S)
    return json.loads(m.group(1) if m else text)


async def lookup_once():
    import aiohttp
    by_host = {}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        mcp = Mcp(session, await _token(session))
        await mcp.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "witness-gateway", "version": "1"}})
        await mcp.call("notifications/initialized", notify=True)
        for iid, typ in parse_instances(await mcp.tool_text("ListInstances")):
            if typ.upper() != "MQTT":
                continue
            st = parse_settings(await mcp.tool_text("GetInstanceSettings", {"id": iid})).get("Settings", {})
            host = str(st.get("Host") or "").lower()
            subs = st.get("Subscriptions") or {}
            for sub in (subs.values() if isinstance(subs, dict) else subs):
                if sub.get("Topic"):
                    flt = topic_prefix_filter(sub["Topic"])
                    if flt not in by_host.setdefault(host, []):
                        by_host[host].append(flt)
    return by_host


async def loop():
    if not STATE["configured"]:
        log.info("Bridge lookup off (no Pulse client): Handoffs leaves out %s on every broker", FALLBACK)
        return
    while True:
        try:
            STATE["byHost"] = await lookup_once()
            STATE["error"] = None
            log.info("Bridge publishes %s", STATE["byHost"] or "nothing to MQTT")
        except Exception as e:  # noqa: BLE001
            STATE["error"] = f"{type(e).__name__}: {e}"
            log.warning("Bridge lookup failed: %s", STATE["error"])
        STATE["checkedAt"] = time.time()
        await asyncio.sleep(LOOKUP_SECONDS)
