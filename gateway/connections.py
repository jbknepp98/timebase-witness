"""Connections the Witness gateway owns: MQTT brokers and OPC UA servers.

Every connection is a record in DATA_DIR/connections.json. Passwords and private keys are encrypted
with Fernet (AES-128-CBC with an HMAC-SHA256 tag) using a key kept in a separate file (KEY_FILE).
If that key is missing, secrets are stored as plain text and the API says so, so the UI can warn
before anyone saves one. Browsers only ever see whether a secret is set, never its value.

Connections can be added, edited, enabled, disabled and removed while the gateway runs; only the
connection being changed reconnects.
"""
import asyncio
import base64
import datetime as dt
import hashlib
import json
import logging
import os
import re
import socket
import ssl
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import aiomqtt
import bridge_lookup
import payload_shapes
import sparkplug
from asyncua import Client, ua
from asyncua.crypto import cert_gen, security_policies as sp
from cryptography import x509
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import ExtendedKeyUsageOID

log = logging.getLogger("lookout-gateway")

DATA_DIR = Path(os.environ.get("LOOKOUT_DATA", "/data/lookout"))
KEY_FILE = Path(os.environ.get("LOOKOUT_KEY_FILE", "/run/lookout/master.key"))
PUBLISH_MS = int(os.environ.get("PUBLISH_MS", "500"))
MAX_NODES = int(os.environ.get("MAX_NODES", "5000"))
MQTT_CACHE_MAX = int(os.environ.get("MQTT_CACHE_MAX", "20000"))
MQTT_STATS_MAX = int(os.environ.get("MQTT_STATS_MAX", "100000"))   # observed MQTT values (topics, JSON leaves, Sparkplug metrics)
DEFAULT_HANDOFF_EXCLUDE = ["$SYS/#"]
CLIENT_APP_URI = "urn:flow-software:lookout-gateway"

POLICIES = {
    "None": None,
    "Basic256Sha256": sp.SecurityPolicyBasic256Sha256,
    "Aes128Sha256RsaOaep": sp.SecurityPolicyAes128Sha256RsaOaep,
    "Aes256Sha256RsaPss": sp.SecurityPolicyAes256Sha256RsaPss,
}
MODES = {"Sign": ua.MessageSecurityMode.Sign, "SignAndEncrypt": ua.MessageSecurityMode.SignAndEncrypt}
SECRET_FIELDS = {"mqtt": ("password", "clientKeyPem"), "opcua": ("password",)}


def observe(stats, key, v, now=None):
    """Running statistics for one observed value: update count, first/last time, min/max, distinct strings."""
    now = now or time.time()
    st = stats.get(key)
    if st is None:
        st = stats[key] = {"n": 0, "first": now, "last": now, "min": None, "max": None, "distinct": set(), "distinctOverflow": False}
    st["n"] += 1
    st["last"] = now
    if isinstance(v, (bool, str)):
        if len(st["distinct"]) < 20:
            st["distinct"].add(str(v))
        elif str(v) not in st["distinct"]:
            st["distinctOverflow"] = True
    elif isinstance(v, (int, float)):
        st["min"] = v if st["min"] is None else min(st["min"], v)
        st["max"] = v if st["max"] is None else max(st["max"], v)


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def jsonable(v):
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return str(v) if (v != v or v in (float("inf"), float("-inf"))) else v
    if isinstance(v, dt.datetime):
        return v.replace(tzinfo=v.tzinfo or dt.timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(v, (bytes, bytearray)):
        return base64.b64encode(bytes(v)).decode()
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, ua.LocalizedText):
        return v.Text
    if isinstance(v, ua.QualifiedName):
        return v.Name
    if isinstance(v, (ua.NodeId, ua.StatusCode)):
        return v.to_string()
    if hasattr(v, "__dict__"):
        return {k: jsonable(x) for k, x in vars(v).items() if not k.startswith("_")}
    return str(v)


def status_of(dv):
    sc = getattr(dv, "StatusCode_", None) or getattr(dv, "StatusCode", None)
    if sc is None:
        return {"code": 0, "name": "Good", "severity": "good"}
    code = sc.value if hasattr(sc, "value") else int(sc)
    sev = (code >> 30) & 0x3
    try:
        name = ua.StatusCode(code).name
    except Exception:  # noqa: BLE001
        name = hex(code)
    return {"code": code, "name": name, "severity": {0: "good", 1: "uncertain"}.get(sev, "bad")}


def thumbprint(der):
    return hashlib.sha1(der).hexdigest().upper() if der else None


# ---------------------------------------------------------------------- secrets
class Vault:
    """Encrypts secrets at rest. The key lives outside the connection store."""

    def __init__(self):
        self.fernet = None
        self.problem = None
        try:
            self.fernet = Fernet(KEY_FILE.read_bytes().strip())
        except FileNotFoundError:
            self.problem = f"No encryption key file at {KEY_FILE}."
        except Exception as e:  # noqa: BLE001
            self.problem = f"The encryption key at {KEY_FILE} is not usable ({type(e).__name__})."
        if self.problem:
            log.warning("secrets will be stored UNENCRYPTED: %s", self.problem)

    def info(self):
        if self.fernet:
            return {"encrypted": True, "method": "Fernet (AES-128-CBC with HMAC-SHA256)",
                    "detail": f"Passwords and private keys are encrypted in {DATA_DIR / 'connections.json'} with a key kept separately in {KEY_FILE}. "
                              "Anyone with administrator access to the Mac Mini can read both files, so this protects copies and backups of the store, not the machine itself."}
        return {"encrypted": False, "method": "plain text",
                "detail": f"{self.problem} Passwords and private keys you save will be stored as plain text in {DATA_DIR / 'connections.json'} on the Mac Mini, "
                          "readable by anyone with access to that file. Add a key file and restart the gateway to encrypt them."}

    def seal(self, plaintext):
        if not plaintext:
            return None
        if self.fernet:
            return {"enc": "fernet", "v": self.fernet.encrypt(plaintext.encode()).decode()}
        return {"enc": "plain", "v": plaintext}

    def open(self, sealed):
        if not sealed:
            return None
        if sealed.get("enc") == "plain":
            return sealed["v"]
        if not self.fernet:
            raise ValueError("a stored secret is encrypted but the gateway has no encryption key")
        try:
            return self.fernet.decrypt(sealed["v"].encode()).decode()
        except InvalidToken as e:
            raise ValueError("a stored secret could not be decrypted with the current key") from e


VAULT = None


def vault():
    global VAULT
    if VAULT is None:
        VAULT = Vault()
    return VAULT


# ---------------------------------------------------------------------- the store
def slug(text):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-") or "connection"


class Store:
    def __init__(self):
        self.path = DATA_DIR / "connections.json"
        self.records = []

    def load(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self.records = json.loads(self.path.read_text())
        except FileNotFoundError:
            self.records = []
        return self.records

    def save(self):
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.records, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def get(self, cid):
        return next((r for r in self.records if r["id"] == cid), None)


def seed_from_env():
    """First start only: turn the old environment settings into stored connections."""
    v = vault()
    out = []
    raw = os.environ.get("OPCUA_SERVERS", "").strip()
    for s in (json.loads(raw) if raw else []):
        user, password = s.get("username", ""), s.get("password", "")
        if not user and s.get("users"):
            user, _, password = s["users"].split(",")[0].partition(":")
        sid = slug(s.get("id") or s.get("name") or urlparse(s["endpoint"]).hostname)
        out.append({"id": sid, "kind": "opcua", "name": s.get("name") or sid, "enabled": True, "createdAt": now_iso(), "updatedAt": now_iso(),
                    "settings": {"endpoint": s["endpoint"], "securityPolicy": "None", "securityMode": "None",
                                 "auth": "username" if user else "anonymous", "username": user, "serverCertThumbprint": "",
                                 "browseRoots": [], "connector": s.get("connector", ""), "publishMs": PUBLISH_MS},
                    "secrets": {"password": v.seal(password)}})
    raw = os.environ.get("MQTT_BROKERS", "").strip()
    for b in (json.loads(raw) if raw else []):
        bid = slug(b.get("id") or b.get("name") or b["host"])
        out.append({"id": bid, "kind": "mqtt", "name": b.get("name") or bid, "enabled": True, "createdAt": now_iso(), "updatedAt": now_iso(),
                    "settings": {"host": b["host"], "port": int(b.get("port", 1883)), "transport": b.get("transport", "tcp"), "wsPath": b.get("wsPath", "/"),
                                 "protocol": b.get("protocol", "3.1.1"), "clientId": "", "username": b.get("username", ""),
                                 "tls": bool(b.get("tls")), "tlsVerify": True, "caPem": "", "clientCertPem": "",
                                 "topics": b.get("topics") or ["#"], "includeSys": b.get("includeSys", True)},
                    "secrets": {"password": v.seal(b.get("password", "")), "clientKeyPem": None}})
    return out


def normalize(kind, body, existing=None):
    """Validate a create/update request. Returns (record, errors). Secrets: non-empty value replaces,
    empty or missing keeps the stored one, clear<Field> = true removes it."""
    errors = {}
    s = body.get("settings") or {}
    old = (existing or {}).get("settings", {})
    name = str(body.get("name") or "").strip()
    if not name:
        errors["name"] = "Give the connection a name."
    elif "/" in name:
        errors["name"] = "A name cannot contain '/'."

    def lines(v):
        if isinstance(v, str):
            v = v.splitlines()
        return [x.strip() for x in (v or []) if str(x).strip()]

    if kind == "mqtt":
        host = str(s.get("host") or "").strip()
        if not host:
            errors["host"] = "Enter the broker's host name or IP address."
        try:
            port = int(s.get("port") or (8883 if s.get("tls") else 1883))
            if not 0 < port < 65536:
                raise ValueError
        except (TypeError, ValueError):
            errors["port"] = "Port must be a number from 1 to 65535."
            port = 1883
        topics = lines(s.get("topics")) or ["#"]
        for t in topics:
            if "#" in t[:-1] or ("#" in t and not (t == "#" or t.endswith("/#"))):
                errors["topics"] = f"'{t}' is not a valid filter: # may only be the last level."
        settings = {"host": host, "port": port, "transport": "websockets" if s.get("transport") == "websockets" else "tcp",
                    "wsPath": str(s.get("wsPath") or "/"), "protocol": "5" if str(s.get("protocol")) == "5" else "3.1.1",
                    "clientId": str(s.get("clientId") or "").strip(), "username": str(s.get("username") or "").strip(),
                    "tls": bool(s.get("tls")), "tlsVerify": s.get("tlsVerify", True) is not False,
                    "caPem": str(s.get("caPem") or "").strip(), "clientCertPem": str(s.get("clientCertPem") or "").strip(),
                    "topics": topics, "includeSys": bool(s.get("includeSys", True)),
                    "handoffExclude": lines(s["handoffExclude"]) if "handoffExclude" in s else list(old.get("handoffExclude", DEFAULT_HANDOFF_EXCLUDE))}
        for t in settings["handoffExclude"]:
            if "#" in t[:-1] or ("#" in t and not (t == "#" or t.endswith("/#"))):
                errors["handoffExclude"] = f"'{t}' is not a valid filter: # may only be the last level."
        for f in ("caPem", "clientCertPem"):
            if settings[f] and "-----BEGIN CERTIFICATE-----" not in settings[f]:
                errors[f] = "Paste a PEM certificate (it starts with -----BEGIN CERTIFICATE-----)."
    elif kind == "opcua":
        endpoint = str(s.get("endpoint") or "").strip()
        if not endpoint.startswith("opc.tcp://"):
            errors["endpoint"] = "The endpoint must start with opc.tcp://"
        policy = s.get("securityPolicy") or "None"
        mode = s.get("securityMode") or "None"
        if policy not in POLICIES:
            errors["securityPolicy"] = "Unsupported security policy."
        if policy == "None":
            mode = "None"
        elif mode not in MODES:
            errors["securityMode"] = "Choose Sign or Sign and encrypt."
        try:
            publish = int(s.get("publishMs") or PUBLISH_MS)
        except (TypeError, ValueError):
            publish = PUBLISH_MS
        settings = {"endpoint": endpoint, "securityPolicy": policy, "securityMode": mode,
                    "auth": "username" if s.get("auth") == "username" else "anonymous", "username": str(s.get("username") or "").strip(),
                    "serverCertThumbprint": re.sub(r"[^0-9A-Fa-f]", "", str(s.get("serverCertThumbprint") or "")).upper(),
                    "browseRoots": [r.strip("/").replace(".", "/") for r in lines(s.get("browseRoots"))],
                    "connector": str(s.get("connector") or "").strip(), "publishMs": max(50, publish)}
        if settings["auth"] == "username" and not settings["username"]:
            errors["username"] = "Enter the user name."
    else:
        return None, {"kind": "Unknown connection type."}

    v = vault()
    old_secrets = (existing or {}).get("secrets", {})
    secrets = {}
    incoming = body.get("secrets") or {}
    for f in SECRET_FIELDS[kind]:
        if incoming.get(f"clear{f[0].upper()}{f[1:]}"):
            secrets[f] = None
        elif incoming.get(f):
            secrets[f] = v.seal(str(incoming[f]))
        else:
            secrets[f] = old_secrets.get(f)
    if kind == "mqtt":
        if settings["clientCertPem"] and not secrets.get("clientKeyPem"):
            errors["clientKeyPem"] = "A client certificate needs its private key."
        if incoming.get("clientKeyPem") and "PRIVATE KEY-----" not in str(incoming["clientKeyPem"]):
            errors["clientKeyPem"] = "Paste a PEM private key (it contains PRIVATE KEY-----)."
    if kind == "opcua" and settings["auth"] == "username" and not secrets.get("password"):
        errors["password"] = "Enter the password."
    rec = dict(existing or {})
    rec.update({"kind": kind, "name": name, "enabled": body.get("enabled", (existing or {}).get("enabled", True)) is not False,
                "settings": settings, "secrets": secrets, "updatedAt": now_iso()})
    rec.setdefault("createdAt", now_iso())
    return rec, errors


def public(rec):
    """What the browser may see: settings, and only whether each secret is set."""
    out = {k: v for k, v in rec.items() if k != "secrets"}
    out["secretsSet"] = {k: bool(v) for k, v in rec.get("secrets", {}).items()}
    out["secretsStorage"] = {k: (v or {}).get("enc") for k, v in rec.get("secrets", {}).items() if v}
    return out


# ---------------------------------------------------------------------- the gateway's OPC UA client certificate
class ClientCert:
    def __init__(self):
        self.dir = DATA_DIR / "pki"
        self.cert = self.dir / "lookout-client-cert.der"
        self.key = self.dir / "lookout-client-key.pem"
        self.thumbprint = None
        self.subject = None
        self.not_after = None

    async def ensure(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        if not (self.cert.exists() and self.key.exists()):
            res = cert_gen.setup_self_signed_certificate(
                self.key, self.cert, CLIENT_APP_URI, "lookout-gateway", [ExtendedKeyUsageOID.CLIENT_AUTH],
                {"countryName": "US", "stateOrProvinceName": "Arkansas", "localityName": "Witness",
                 "organizationName": "Flow Software", "commonName": "Timebase Witness gateway"})
            if asyncio.iscoroutine(res):
                await res
            os.chmod(self.key, 0o600)
            log.info("created OPC UA client certificate %s", self.cert)
        der = self.cert.read_bytes()
        try:
            c = x509.load_der_x509_certificate(der)
        except ValueError:
            c = x509.load_pem_x509_certificate(der)
            der = c.public_bytes(serialization.Encoding.DER)
        self.der = der
        self.thumbprint = thumbprint(der)
        self.subject = c.subject.rfc4514_string()
        self.not_after = c.not_valid_after_utc.isoformat() if hasattr(c, "not_valid_after_utc") else str(c.not_valid_after)

    def info(self):
        return {"thumbprint": self.thumbprint, "subject": self.subject, "applicationUri": CLIENT_APP_URI, "notAfter": self.not_after}


CLIENT_CERT = ClientCert()


# ---------------------------------------------------------------------- OPC UA
async def apply_opcua_security(client, settings, password):
    client.application_uri = CLIENT_APP_URI
    client.name = "Timebase Witness gateway"
    policy = POLICIES.get(settings["securityPolicy"])
    if policy:
        await client.set_security(policy, certificate=str(CLIENT_CERT.cert), private_key=str(CLIENT_CERT.key),
                                  mode=MODES[settings["securityMode"]])
    if settings["auth"] == "username":
        client.set_user(settings["username"])
        client.set_password(password or "")


async def check_pinned_server_cert(settings):
    want = settings.get("serverCertThumbprint")
    if not want:
        return
    eps = await discover(settings["endpoint"], raw=True)
    seen = {thumbprint(ep.ServerCertificate) for ep in eps}
    if want not in seen:
        raise ConnectionError(f"The server presented certificate {', '.join(sorted(t for t in seen if t)) or 'none'}, not the trusted {want}. "
                              "If the server's certificate changed on purpose, trust the new one in this connection's settings.")


async def discover(endpoint, raw=False):
    client = Client(url=endpoint, timeout=8)
    eps = await asyncio.wait_for(client.connect_and_get_server_endpoints(), 15)
    if raw:
        return eps
    out = []
    for ep in eps:
        out.append({"endpointUrl": ep.EndpointUrl, "policy": (ep.SecurityPolicyUri or "").split("#")[-1] or "None",
                    "mode": ep.SecurityMode.name.rstrip("_"), "securityLevel": ep.SecurityLevel,
                    "userTokens": sorted({t.TokenType.name for t in ep.UserIdentityTokens}),
                    "serverCertThumbprint": thumbprint(ep.ServerCertificate),
                    "server": ep.Server.ApplicationName.Text if ep.Server and ep.Server.ApplicationName else None})
    return out


class OpcUaConn:
    kind = "opcua"

    def __init__(self, rec, hub):
        self.hub = hub
        self.rec = rec
        self.id = rec["id"]
        s = rec["settings"]
        self.cfg = {"name": rec["name"], "endpoint": s["endpoint"], "user": s["username"] if s["auth"] == "username" else "",
                    "connector": s.get("connector", "")}
        self.state = "disabled" if not rec.get("enabled", True) else "starting"
        self.error = None
        self.nodes, self.values, self.pending, self.stats = {}, {}, {}, {}
        self.updates = 0
        self.connected_at = None
        self.server_info = {}
        self.tasks = []

    # browse --------------------------------------------------------------
    def _wanted(self, path):
        roots = self.rec["settings"].get("browseRoots") or []
        if not roots:
            return True
        return any(path == r or path.startswith(r + "/") or r.startswith(path + "/") for r in roots)

    async def crawl(self, client):
        dtype_names, nodes, order = {}, {}, []

        async def dtype_name(nid):
            key = nid.to_string()
            if key not in dtype_names:
                try:
                    dtype_names[key] = (await client.get_node(nid).read_browse_name()).Name
                except Exception:  # noqa: BLE001
                    dtype_names[key] = key
            return dtype_names[key]

        async def walk(node, path, parent_id, depth):
            if len(nodes) >= MAX_NODES or depth > 12:
                return
            refs = await node.get_references(
                refs=ua.ObjectIds.HierarchicalReferences, direction=ua.BrowseDirection.Forward,
                nodeclassmask=ua.NodeClass.Object | ua.NodeClass.Variable, includesubtypes=True)
            for ref in refs:
                if ref.ReferenceTypeId == ua.NodeId(ua.ObjectIds.HasProperty):
                    continue
                nid = ref.NodeId
                if depth == 0 and nid.NamespaceIndex == 0:
                    continue
                key = nid.to_string()
                if key in nodes:
                    continue
                name = ref.BrowseName.Name
                child_path = f"{path}/{name}" if path else name
                if not self._wanted(child_path):
                    continue
                info = {"id": key, "path": child_path, "name": name, "displayName": ref.DisplayName.Text or name,
                        "nodeClass": "Variable" if ref.NodeClass == ua.NodeClass.Variable else "Object", "parent": parent_id}
                nodes[key] = info
                order.append(key)
                child = client.get_node(nid)
                try:
                    desc = await child.read_description()
                    if desc and desc.Text:
                        info["description"] = desc.Text
                except Exception:  # noqa: BLE001
                    pass
                if info["nodeClass"] == "Variable":
                    try:
                        info["dataType"] = await dtype_name(await child.read_data_type())
                        lvl = await child.read_attribute(ua.AttributeIds.UserAccessLevel)
                        info["writable"] = bool(int(lvl.Value.Value) & 0x2)
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        for prop in await child.get_properties():
                            pname = (await prop.read_browse_name()).Name
                            if pname == "EngineeringUnits":
                                eu = await prop.read_value()
                                info["units"] = getattr(getattr(eu, "DisplayName", None), "Text", None) or str(eu)
                            elif pname == "EURange":
                                r = await prop.read_value()
                                info["range"] = [r.Low, r.High]
                    except Exception:  # noqa: BLE001
                        pass
                await walk(child, child_path, key, depth + 1)

        await walk(client.nodes.objects, "", None, 0)
        return {k: nodes[k] for k in order}

    # subscription callbacks ---------------------------------------------
    def datachange_notification(self, node, val, data):
        dv = data.monitored_item.Value
        key = node.nodeid.to_string()
        msg = {"id": key, "v": jsonable(dv.Value.Value if dv.Value is not None else None), "q": status_of(dv),
               "st": jsonable(dv.SourceTimestamp) if dv.SourceTimestamp else None,
               "svt": jsonable(dv.ServerTimestamp) if dv.ServerTimestamp else None, "rt": int(time.time() * 1000)}
        self.values[key] = msg
        self.pending[key] = msg
        self.updates += 1
        self.observe(key, msg["v"])

    def status_change_notification(self, status):
        log.warning("[%s] subscription status change: %s", self.id, status)

    def observe(self, key, v):
        observe(self.stats, key, v)

    # lifecycle ------------------------------------------------------------
    def start(self):
        if self.rec.get("enabled", True):
            self.tasks = [asyncio.create_task(self.run()), asyncio.create_task(self.flusher())]

    async def stop(self):
        for t in self.tasks:
            t.cancel()
        for t in self.tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self.tasks = []

    async def run(self):
        backoff = 2
        while True:
            s = self.rec["settings"]
            client = Client(url=s["endpoint"], timeout=10)
            try:
                self.set_state("connecting")
                password = vault().open(self.rec["secrets"].get("password"))
                await check_pinned_server_cert(s)
                await apply_opcua_security(client, s, password)
                await client.connect()
                try:
                    bi = await (await client.nodes.server.get_child(["0:ServerStatus", "0:BuildInfo"])).read_value()
                    self.server_info = {"product": bi.ProductName, "version": bi.SoftwareVersion, "manufacturer": bi.ManufacturerName}
                except Exception:  # noqa: BLE001
                    self.server_info = {}
                self.set_state("browsing")
                self.nodes = await self.crawl(client)
                self.values, self.stats = {}, {}
                variables = [client.get_node(k) for k, n in self.nodes.items() if n["nodeClass"] == "Variable"]
                sub = await client.create_subscription(s.get("publishMs") or PUBLISH_MS, self)
                for i in range(0, len(variables), 500):
                    await sub.subscribe_data_change(variables[i:i + 500], queuesize=10)
                self.connected_at = time.time()
                self.set_state("connected")
                log.info("[%s] connected to %s (%s/%s): %d nodes, %d variables", self.id, s["endpoint"],
                         s["securityPolicy"], s["securityMode"], len(self.nodes), len(variables))
                await self.hub.broadcast(self.model())
                backoff = 2
                while True:
                    await asyncio.sleep(3)
                    await client.check_connection()
            except asyncio.CancelledError:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
                raise
            except Exception as exc:  # noqa: BLE001
                self.error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                log.warning("[%s] OPC UA connection problem: %s", self.id, self.error)
                self.set_state("disconnected")
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    def set_state(self, state):
        self.state = state
        if state == "connected":
            self.error = None
        asyncio.get_event_loop().create_task(self.hub.broadcast({"type": "status", **self.status()}))

    def status(self):
        s = self.rec["settings"]
        return {"server": self.id, "id": self.id, "kind": "opcua", "name": self.rec["name"], "enabled": self.rec.get("enabled", True),
                "endpoint": s["endpoint"], "state": self.state, "error": self.error, "serverInfo": self.server_info,
                "nodes": len(self.nodes), "variables": sum(1 for n in self.nodes.values() if n["nodeClass"] == "Variable"),
                "updates": self.updates, "connectedAt": self.connected_at, "publishMs": s.get("publishMs") or PUBLISH_MS,
                "user": self.cfg["user"] or None, "connector": s.get("connector") or None,
                "security": {"policy": s["securityPolicy"], "mode": s["securityMode"], "pinned": bool(s.get("serverCertThumbprint"))},
                "browseRoots": s.get("browseRoots") or []}

    def model(self):
        return {"type": "model", "server": self.id, "status": self.status(), "nodes": list(self.nodes.values()), "values": list(self.values.values())}

    def snapshot(self):
        return self.model()

    async def flusher(self):
        while True:
            await asyncio.sleep(0.25)
            if self.pending:
                items = list(self.pending.values())
                self.pending = {}
                await self.hub.broadcast({"type": "values", "server": self.id, "items": items})


# ---------------------------------------------------------------------- MQTT
def mqtt_tls_context(s, key_pem):
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    if s.get("caPem"):
        ctx.load_verify_locations(cadata=s["caPem"])
    if s.get("clientCertPem") and key_pem:
        # ssl can only load a certificate chain from files: write them briefly with owner-only permissions
        with tempfile.TemporaryDirectory(dir=DATA_DIR) as d:
            cf, kf = Path(d) / "c.pem", Path(d) / "k.pem"
            cf.write_text(s["clientCertPem"])
            kf.write_text(key_pem)
            os.chmod(kf, 0o600)
            ctx.load_cert_chain(cf, kf)
    if not s.get("tlsVerify", True):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def mqtt_client(rec, identifier=None):
    s = rec["settings"]
    password = vault().open(rec["secrets"].get("password"))
    key_pem = vault().open(rec["secrets"].get("clientKeyPem"))
    return aiomqtt.Client(
        s["host"], int(s["port"]), username=s["username"] or None, password=password or None,
        identifier=identifier or s.get("clientId") or f"lookout-{uuid.uuid4().hex[:8]}",
        protocol=aiomqtt.ProtocolVersion.V5 if s.get("protocol") == "5" else aiomqtt.ProtocolVersion.V311,
        transport=s.get("transport", "tcp"), websocket_path=(s.get("wsPath") or "/") if s.get("transport") == "websockets" else None,
        tls_context=mqtt_tls_context(s, key_pem) if s.get("tls") else None, keepalive=30, timeout=10)


def mqtt_filters(s):
    topics = list(s.get("topics") or ["#"])
    if s.get("includeSys", True) and not any(t.startswith("$SYS") for t in topics):
        topics.append("$SYS/#")
    return topics


def mqtt_entry(message, spb=None):
    """One message for the browser. Sparkplug B payloads are decoded to JSON (names and datatypes
    resolved against the Edge Node's births in `spb`); a payload that fails to decode stays base64."""
    raw = bytes(message.payload) if message.payload is not None else b""
    topic = message.topic.value
    e = {"t": topic, "r": bool(message.retain), "q": int(message.qos), "ts": int(time.time() * 1000)}
    info = sparkplug.parse_topic(topic)
    if info and info["type"] != "STATE" and spb is not None:
        try:
            decoded = spb.apply(info, sparkplug.parse(raw))
            e.update({"p": json.dumps(decoded, separators=(",", ":"), default=str), "b": False,
                      "spb": {k: info[k] for k in ("type", "group", "node", "device")}})
            return e
        except Exception as exc:  # noqa: BLE001  (a malformed payload must never stop the connection)
            e["spbError"] = f"{type(exc).__name__}: {exc}"
    try:
        e["p"], e["b"] = raw.decode("utf-8"), False
    except UnicodeDecodeError:
        e["p"], e["b"] = base64.b64encode(raw).decode(), True
    return e


def spb_values(metrics, prefix=""):
    """(name, value) for Sparkplug metrics, template members flattened as instance.member like Collector."""
    for m in metrics:
        name = m.get("name")
        if not name:
            continue
        t = m.get("template")
        if t is not None:
            if not t.get("definition"):
                yield from spb_values(t.get("metrics", []), f"{prefix}{name}.")
        elif not isinstance(m.get("value"), (dict, list)):
            yield prefix + name, m.get("value")


def mqtt_url(s):
    scheme = ("wss" if s.get("tls") else "ws") if s.get("transport") == "websockets" else ("mqtts" if s.get("tls") else "mqtt")
    return f"{scheme}://{s['host']}:{s['port']}" + ((s.get("wsPath") or "/") if s.get("transport") == "websockets" else "")


class MqttConn:
    kind = "mqtt"

    def __init__(self, rec, hub):
        self.hub = hub
        self.rec = rec
        self.id = rec["id"]
        self.state = "disabled" if not rec.get("enabled", True) else "starting"
        self.error = None
        self.cache = {}
        self.pending = []
        self.spb = sparkplug.NodeSessions()   # Sparkplug B births, aliases and template definitions per Edge Node
        self.stats = {}                       # observed values: topic, topic\x1fJSON leaf, or spb:<group/node[/device]>\x1fmetric
        self.shapes = {}                      # topic -> payload shape of its latest message (payload_shapes.classify)
        self.stats_truncated = False
        self.updates = 0
        self.connected_at = None
        self.tasks = []

    def start(self):
        if self.rec.get("enabled", True):
            self.tasks = [asyncio.create_task(self.run()), asyncio.create_task(self.flusher())]

    async def stop(self):
        for t in self.tasks:
            t.cancel()
        for t in self.tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self.tasks = []

    async def run(self):
        backoff = 2
        while True:
            try:
                self.set_state("connecting")
                async with mqtt_client(self.rec) as client:
                    for t in mqtt_filters(self.rec["settings"]):
                        await client.subscribe(t, qos=0)
                    self.connected_at = time.time()
                    self.spb = sparkplug.NodeSessions()   # a new connection starts every Sparkplug session afresh
                    self.shapes = {}
                    self.set_state("connected")
                    backoff = 2
                    log.info("[%s] connected to %s", self.id, mqtt_url(self.rec["settings"]))
                    async for message in client.messages:
                        e = mqtt_entry(message, self.spb)
                        self.observe_entry(e)
                        if e["p"] == "" and e["r"]:
                            self.cache.pop(e["t"], None)
                        elif e["t"] in self.cache or len(self.cache) < MQTT_CACHE_MAX:
                            self.cache[e["t"]] = e
                        self.pending.append(e)
                        self.updates += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                log.warning("[%s] MQTT connection problem: %s", self.id, self.error)
                self.set_state("disconnected")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    def set_state(self, state):
        self.state = state
        if state == "connected":
            self.error = None
        asyncio.get_event_loop().create_task(self.hub.broadcast({"type": "status", **self.status()}))

    def status(self):
        s = self.rec["settings"]
        return {"id": self.id, "kind": "mqtt", "name": self.rec["name"], "enabled": self.rec.get("enabled", True),
                "endpoint": mqtt_url(s), "state": self.state, "error": self.error, "user": s.get("username") or None,
                "topics": mqtt_filters(s), "updates": self.updates, "connectedAt": self.connected_at,
                "cachedTopics": len(self.cache), "security": {"tls": bool(s.get("tls")), "verify": s.get("tlsVerify", True),
                                                             "clientCert": bool(s.get("clientCertPem"))},
                "handoffExclude": s.get("handoffExclude", DEFAULT_HANDOFF_EXCLUDE),
                "bridgeExclude": bridge_lookup.bridge_excludes(s)}

    def snapshot(self):
        return {"type": "mqtt_snapshot", "conn": self.id, "msgs": list(self.cache.values())}

    # observation for Handoffs ------------------------------------------
    def _obs(self, key, v):
        if key in self.stats or len(self.stats) < MQTT_STATS_MAX:
            observe(self.stats, key, v)
        else:
            self.stats_truncated = True

    def observe_entry(self, e):
        """Record the message's shape and observe its values (never raises: observation must not stop the feed)."""
        t = e["t"]
        try:
            sh = payload_shapes.classify(t, e)
            if sh is None:
                self.shapes.pop(t, None)
                return
            if t in self.shapes or len(self.shapes) < MQTT_CACHE_MAX:
                self.shapes[t] = sh
            kind = sh["shape"]
            if kind == "Simple":
                text = e["p"].strip()
                typ = sh["detail"]["valueType"]
                self._obs(t, float(text) if typ == "Double" else (text.lower() == "true" if typ == "Boolean" else text))
            elif kind == "JsonValueObject":
                self._obs(t, json.loads(e["p"])[sh["detail"]["valueField"]])
            elif kind == "JsonRecord":
                for path, v in payload_shapes.flatten(json.loads(e["p"])):
                    self._obs(f"{t}\x1f{payload_shapes.path_text(path)}", v)
            elif kind == "JsonMetricsArray":
                d = sh["detail"]
                arr = json.loads(e["p"])
                for k in [x for x in d["arrayPath"].split(".") if x]:
                    arr = arr[k]
                for el in arr:
                    self._obs(f"{t}\x1f{el.get(d['nameField'])}", el.get(d["valueField"]))
            elif kind == "SparkplugB":
                info = e["spb"]
                scope = "/".join(x for x in (info.get("group"), info.get("node"), info.get("device")) if x)
                for name, v in spb_values(json.loads(e["p"]).get("metrics", [])):
                    self._obs(f"spb:{scope}\x1f{name}", v)
        except Exception as exc:  # noqa: BLE001
            log.debug("[%s] could not observe %s: %s", self.id, t, exc)

    def profile_inputs(self):
        """Everything the Handoffs source model needs from this broker."""
        return {"cache": self.cache, "stats": self.stats, "shapes": self.shapes, "spb": self.spb,
                "connectedAt": self.connected_at, "statsTruncated": self.stats_truncated,
                "exclude": bridge_lookup.effective_excludes(self.rec["settings"])}

    async def flusher(self):
        while True:
            await asyncio.sleep(0.1)
            if self.pending:
                msgs, self.pending = self.pending, []
                await self.hub.broadcast({"type": "mqtt", "conn": self.id, "msgs": msgs})


# ---------------------------------------------------------------------- testing settings before saving
async def test_connection(rec):
    s = rec["settings"]
    started = time.time()
    if rec["kind"] == "mqtt":
        seen = {}
        async with mqtt_client(rec, identifier=f"lookout-test-{uuid.uuid4().hex[:6]}") as client:
            for t in mqtt_filters(s):
                await client.subscribe(t, qos=0)
            try:
                async with asyncio.timeout(3):
                    async for m in client.messages:
                        seen[m.topic.value] = seen.get(m.topic.value, 0) + 1
            except TimeoutError:
                pass
        user = [t for t in seen if not t.startswith("$SYS")]
        return {"ok": True, "message": f"Connected to {mqtt_url(s)} and received {sum(seen.values())} messages on {len(user)} topics in 3 seconds"
                + (" (plus broker $SYS topics)" if len(user) < len(seen) else "") + ".",
                "sample": sorted(user)[:12], "ms": int((time.time() - started) * 1000)}
    password = vault().open(rec["secrets"].get("password"))
    await check_pinned_server_cert(s)
    client = Client(url=s["endpoint"], timeout=10)
    await apply_opcua_security(client, s, password)
    await client.connect()
    try:
        info = {}
        try:
            bi = await (await client.nodes.server.get_child(["0:ServerStatus", "0:BuildInfo"])).read_value()
            info = {"product": bi.ProductName, "version": bi.SoftwareVersion}
        except Exception:  # noqa: BLE001
            pass
        top = [c for c in await client.nodes.objects.get_children() if c.nodeid.NamespaceIndex != 0]
        names = [(await c.read_browse_name()).Name for c in top[:20]]
    finally:
        await client.disconnect()
    prod = f"{info.get('product')} {info.get('version') or ''}".strip() if info else "the server"
    return {"ok": True, "message": f"Connected to {prod} with security {s['securityPolicy']}"
            + (f" / {s['securityMode']}" if s["securityPolicy"] != "None" else "")
            + (f" as {s['username']}" if s["auth"] == "username" else " anonymously") + ".",
            "sample": names, "ms": int((time.time() - started) * 1000)}
