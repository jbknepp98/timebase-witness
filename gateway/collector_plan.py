"""Collector plans for Handoffs: check the agent's plan against the source and write the settings.

A plan (v2) is {dataset, instances: [{plugin: OPCUA|MQTT|SparkplugB, name, subscriptions, notes}], notes}:
every instance writes to the one dataset, which one Connect Historian connector serves. The v1 shape
(an OPC UA plan: {name, dataset, subscriptions}) is still accepted and becomes one OPCUA instance.

For MQTT and SparkplugB, Witness predicts every tag with collector_naming from the messages it has
seen, fills in payload settings the agent left out from the detected payload shapes, and reports
problems (topics that match nothing, a subscription type that does not fit its payloads, JSON Simple
array collisions, two subscriptions writing the same tag, excluded or metadata topics). Connection
settings come from the Witness connection; a password is never exported.

The OPCUA functions further down (validate_collector, collector_instance, connect_plan) are the
original OPC UA path, unchanged, so existing OPC UA plans give the same results.
"""
import os
import re
from collections import defaultdict

import collector_naming as cn
import payload_shapes as ps
from source_model import units_of

# Witness's policy names -> Timebase Collector OPC UA plugin names
COLLECTOR_POLICY = {"None": "None", "Basic256Sha256": "Basic256Sha256",
                    "Aes128Sha256RsaOaep": "Aes128_Sha256_RsaOaep", "Aes256Sha256RsaPss": "Aes256_Sha256_RsaPss"}
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def topic_matches(pattern, path):
    """Collector OPC UA topic match: dot-delimited, case-sensitive, + one level, # the rest (last only)."""
    pat, segs = pattern.split("."), path.split(".")
    for i, p in enumerate(pat):
        if p == "#":
            return i < len(segs)
        if i >= len(segs) or (p != "+" and p != segs[i]):
            return False
    return len(pat) == len(segs)


def validate_collector(server, plan):
    """Check the model's plan against the namespace. Returns (report, problems)."""
    variables = sorted(n["path"].replace("/", ".") for n in server.nodes.values() if n["nodeClass"] == "Variable")
    problems, subs = [], []
    if not NAME_RE.match(plan.get("name") or ""):
        problems.append("name must be PascalCase letters and digits, starting with a letter")
    if not NAME_RE.match(plan.get("dataset") or ""):
        problems.append("dataset must be PascalCase letters and digits, starting with a letter")
    if not plan.get("subscriptions"):
        problems.append("at least one subscription is needed")
    logged = set()
    owner = {}
    for i, sub in enumerate(plan.get("subscriptions") or []):
        topics = [t.strip() for t in sub.get("topics") or [] if t.strip()]
        rep = {"subscription": i + 1, "topics": {}}
        if not topics:
            problems.append(f"subscription {i + 1} has no topics")
        for t in topics:
            if "/" in t:
                problems.append(f"topic '{t}' uses '/'; Collector topics are dot-joined")
            if "#" in t[:-1] or ("#" in t and not t.endswith(".#") and t != "#"):
                problems.append(f"topic '{t}': '#' may only be the last segment")
            n = sum(1 for v in variables if topic_matches(t, v))
            rep["topics"][t] = n
            if n == 0:
                problems.append(f"topic '{t}' matches no variable in the namespace")
        matched = [v for v in variables if any(topic_matches(t, v) for t in topics)]
        rx = sub.get("excludeRegex") or ""
        excluded = []
        if rx:
            try:
                r = re.compile(rx)
                excluded = [v for v in matched if r.search(v)]
            except re.error as e:
                problems.append(f"subscription {i + 1} excludeRegex does not compile: {e}")
        kept = [v for v in matched if v not in excluded]
        logged.update(kept)
        for v in kept:
            owner.setdefault(v, i)
        td = sub.get("topicDefinition") or ""
        keys = [k for k in td.split(".") if k]
        if not keys:
            problems.append(f"subscription {i + 1} needs a topicDefinition")
        for f in sub.get("fields") or []:
            for key in re.findall(r"\[Topic:([^\]]+)\]", f.get("value") or ""):
                if key not in keys:
                    problems.append(f"field {f.get('name')} uses [Topic:{key}] but topicDefinition has no '{key}' segment")
        depths = sorted({len(v.split(".")) for v in kept})
        if keys and depths and len(keys) > max(depths):
            problems.append(f"topicDefinition has {len(keys)} segments but the longest logged path has {max(depths)}")
        if sub.get("intervalMs") is not None and not (50 <= int(sub["intervalMs"]) <= 3_600_000):
            problems.append(f"subscription {i + 1} intervalMs should be between 50 and 3600000")
        rep.update({"matched": len(matched), "excluded": len(excluded), "logged": len(kept),
                    "pathDepths": depths, "sampleExcluded": excluded[:12], "sampleLogged": kept[:8]})
        subs.append(rep)
    report = {"ok": not problems, "problems": problems, "variablesInNamespace": len(variables),
              "variablesLogged": len(logged), "notLogged": [v for v in variables if v not in logged][:25], "subscriptions": subs}
    report["_owner"] = owner      # tag -> subscription index; run_tool strips it before the model sees the report
    return report, problems


def collector_instance(server, plan, report):
    """The Collector instance as a settings document: connection from Witness, the rest from the plan."""
    st = server.status()
    s = server.rec["settings"]
    policy = s.get("securityPolicy") or "None"
    settings = {"Url": s["endpoint"]}
    if s.get("auth") == "username" and s.get("username"):
        settings["Username"] = s["username"]
    settings["SecurityPolicy"] = COLLECTOR_POLICY.get(policy, policy)
    settings["SecurityMode"] = s.get("securityMode") if policy != "None" else "None"
    if policy != "None":
        # Witness pins the server certificate when the user asked it to; Collector has no pin, so
        # keep the same stance: trust it explicitly instead of auto-accepting.
        settings["AutoAcceptUntrusted"] = not bool(s.get("serverCertThumbprint"))
    subs = []
    for sub in plan["subscriptions"]:
        out = {"Interval": int(sub.get("intervalMs") or 1000),
               "Topics": [t.strip() for t in sub["topics"] if t.strip()],
               "TopicDefinition": sub["topicDefinition"]}
        if sub.get("excludeRegex"):
            out["Filter"] = sub["excludeRegex"]
        out["Fields"] = {f["name"]: f["value"] for f in sub.get("fields") or [] if f.get("name")}
        subs.append(out)
    settings["Subscriptions"] = subs
    return {
        "name": plan["name"], "type": "OPCUA",
        "description": f"{st['name']} ({s['endpoint']}) - planned by Witness",
        "historian": {"dataset": plan["dataset"]},
        "Settings": settings,
        "needsPassword": s.get("auth") == "username",
        "trustServerCertificate": s.get("serverCertThumbprint") or None,
        "variablesLogged": report["variablesLogged"],
        "notes": plan.get("notes") or [],
    }




HISTORIAN_HOST = os.environ.get("CONNECT_HISTORIAN_HOST", "historian")
HISTORIAN_PORT = int(os.environ.get("CONNECT_HISTORIAN_PORT", "4512"))
HISTORIAN_TLS = os.environ.get("CONNECT_HISTORIAN_TLS", "true").lower() not in ("0", "false", "no")


def tag_fields(tag, sub):
    """The metadata fields Collector writes on a tag, from the subscription's topic definition and fields."""
    keys = [k for k in (sub.get("TopicDefinition") or "").split(".") if k]
    segs = tag.split(".")
    seg = {k: segs[i] for i, k in enumerate(keys) if i < len(segs)}
    return {name: re.sub(r"\[Topic:([^\]]+)\]", lambda m: seg.get(m.group(1), m.group(0)), str(val))
            for name, val in (sub.get("Fields") or {}).items()}


def connect_plan(server, inst, owner):
    """The Connect handoff: a Historian connector for the Collector's dataset, and what that dataset holds."""
    dataset = inst["historian"]["dataset"]
    subs = inst["Settings"]["Subscriptions"]
    by_tag = {n["path"].replace("/", "."): n for n in server.nodes.values() if n["nodeClass"] == "Variable"}
    tags = []
    for tag in sorted(owner):
        n = by_tag.get(tag) or {}
        tags.append({"name": tag, "dataType": n.get("dataType") or "?", "units": units_of(n) if n else None,
                     "fields": tag_fields(tag, subs[owner[tag]]), "parent": tag.rsplit(".", 1)[0], "signal": tag.rsplit(".", 1)[-1]})
    types, units = defaultdict(int), defaultdict(int)
    for t in tags:
        types[t["dataType"]] += 1
        if t["units"]:
            units[t["units"]] += 1
    # fields per subscription: each has its own topic definition, so its tags carry their own field set
    fields = []
    for i, sub in enumerate(subs):
        mine = [t for t in tags if owner[t["name"]] == i]
        values = defaultdict(set)
        for t in mine:
            for k, v in t["fields"].items():
                values[k].add(v)
        fields.append({"topics": sub["Topics"], "topicDefinition": sub.get("TopicDefinition") or "", "tags": len(mine),
                       "fields": [{"name": k, "distinct": len(v), "examples": sorted(v)[:6]} for k, v in values.items()]})
    # one sample object per signal pattern (objects that log the same set of signals)
    groups = defaultdict(list)
    for t in tags:
        groups[t["parent"]].append(t)
    patterns = defaultdict(list)
    for parent, ts in groups.items():
        patterns[tuple(sorted(x["signal"] for x in ts))].append(parent)
    samples = []
    for sig, parents in sorted(patterns.items(), key=lambda kv: -len(kv[1]))[:8]:
        first = sorted(parents)[0]
        samples.append({"objects": len(parents), "example": first, "tags": sorted(groups[first], key=lambda x: x["name"])[:12]})
    settings = {"Host": HISTORIAN_HOST, "Port": HISTORIAN_PORT, "UseTls": HISTORIAN_TLS,
                "ClientName": f"Timebase.Connect.{dataset}", "Auth": {"Mode": "Host"},
                "Datasets": {dataset: {"Dataset": dataset}}, "DefaultLookback": "01:00:00"}
    return {"name": f"Historian {dataset}", "type": "Timebase.Historian", "dataset": dataset, "collector": inst["name"],
            "Settings": settings, "tagCount": len(tags), "dataTypes": dict(types), "units": dict(units),
            "fields": fields, "samples": samples, "maxDepth": max((t["name"].count(".") + 1 for t in tags), default=0)}




# ====================================================================== plans with several instances (v2)
PLUGINS = ("OPCUA", "MQTT", "SparkplugB")
SHAPE_TYPE = {"Simple": "Simple", "JsonValueObject": "JsonStructured", "JsonMetricsArray": "JsonStructured", "JsonRecord": "JsonSimple"}


def to_v2(plan):
    if isinstance(plan, dict) and "instances" in plan:
        return plan
    plan = plan or {}
    return {"dataset": plan.get("dataset"), "notes": plan.get("notes") or [],
            "instances": [{"plugin": "OPCUA", "name": plan.get("name"), "subscriptions": plan.get("subscriptions") or [], "notes": []}]}


def _fields(f):
    if isinstance(f, dict):
        return {str(k): str(v) for k, v in f.items()}
    return {x.get("name"): str(x.get("value", "")) for x in (f or []) if isinstance(x, dict) and x.get("name")}


def _lines(v):
    if isinstance(v, str):
        v = [v]
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def mqtt_subscription(sub, shapes):
    """Agent subscription -> Collector MQTT subscription, with payload settings the agent left out taken
    from the shapes of the topics it matches. Returns (settings, majority shape or None)."""
    topics = _lines(sub.get("topics"))
    matched = [sh for t, sh in shapes.items() if ps.any_match(topics, t)]
    counts = defaultdict(int)
    for sh in matched:
        counts[sh["shape"]] += 1
    shape = max(counts, key=counts.get) if counts else None
    d = next((sh["detail"] for sh in matched if sh["shape"] == shape), {}) if shape else {}
    typ = sub.get("type") or SHAPE_TYPE.get(shape, "Simple")
    out = {"Type": typ, "QoS": sub.get("qos") or "AtLeastOnce", "Topics": topics}
    if sub.get("topicDefinition"):
        out["TopicDefinition"] = sub["topicDefinition"]
    out["TagnameDelimiter"] = sub.get("tagnameDelimiter") if sub.get("tagnameDelimiter") is not None else "."
    if typ != "Simple":
        arr = shape == "JsonMetricsArray"
        out["TagnameIncludesTopic"] = sub["tagnameIncludesTopic"] if sub.get("tagnameIncludesTopic") is not None else not arr
        tf = sub.get("tagnameFields") or ([d["nameField"]] if arr and d.get("nameField") else [])
        if tf:
            out["TagnameFields"] = list(tf)
        ts = sub.get("timestampFields") or ([d["timestampField"]] if d.get("timestampField") else []) or \
            ([k for k in d.get("timestampKeys", []) if "[" not in k][:3] if typ == "JsonSimple" else [])
        if ts:
            out["TimestampFields"] = list(ts)
            out["TimestampType"] = sub.get("timestampType") or d.get("timestampType") or _guess_ts_type(d, ts)
    if typ == "JsonStructured":
        out["ValueField"] = sub.get("valueField") or d.get("valueField") or "value"
        q = sub.get("qualityField") or d.get("qualityField")
        if q:
            out["QualityField"] = q
        # units are optional per message, so take the unit field from any matched topic that has one
        uf = next((sh["detail"].get("uomField") for sh in matched if sh["shape"] == shape and sh["detail"].get("uomField")), None)
        u = sub.get("uomFields") or ([uf] if uf else [])
        if u:
            out["UOMFields"] = list(u)
    if sub.get("ignoreParts"):
        out["IgnoreParts"] = _lines(sub["ignoreParts"])
    out["Filter"] = sub.get("excludeRegex") or ""
    out["Fields"] = _fields(sub.get("fields"))
    return out, shape


def _guess_ts_type(d, ts):
    leaves = {x["path"]: x for x in d.get("leaves", [])}
    return "String" if any((leaves.get(t) or {}).get("type") == "String" for t in ts) else "UNIXMilliseconds"


def spb_subscription(sub):
    return {"Type": "Simple", "QoS": sub.get("qos") or "AtLeastOnce", "Topics": _lines(sub.get("topics")),
            **({"IgnoreParts": _lines(sub["ignoreParts"])} if sub.get("ignoreParts") else {}),
            "Filter": sub.get("excludeRegex") or "", "SkipBirthAndSequenceValidation": False,
            "IncludeTransientMetrics": bool(sub.get("includeTransient")),
            "IncludeHousekeepingMetrics": sub.get("includeHousekeeping") is not False}


def broker_connection(rec):
    """Collector MQTT / SparkplugB connection settings from a Witness broker connection (never the password)."""
    s = rec["settings"]
    out = {"Host": s["host"], "Port": int(s["port"]), "UseTls": bool(s.get("tls"))}
    if s.get("tls") and s.get("tlsVerify") is False:
        out["DisableHostnameVerification"] = True
    if s.get("username"):
        out["Username"] = s["username"]
    notes = []
    if s.get("tls") and s.get("caPem"):
        notes.append("Witness trusts this broker through a custom CA certificate. Collector must trust the same CA "
                     "(add it to the Collector container's trust store), or use the broker's plain port on the Timebase network.")
    if s.get("clientCertPem"):
        notes.append("Witness signs in to this broker with a client certificate. Give Collector its own client certificate "
                     "(Certificate settings); Witness does not export keys.")
    if s.get("transport") == "websockets":
        notes.append("Witness reaches this broker over WebSockets; Collector's MQTT plugin uses TCP, so use the broker's TCP port.")
    notes.append(f"Collector reaches the broker as `{s['host']}` on the Timebase network, the name Witness uses; change Host if Collector sees it under another name.")
    return out, bool((rec.get("secrets") or {}).get("password")), notes


def validate(conn, plan, inputs=None):
    """Check a v1 or v2 plan against a connection.
    Returns {"report", "problems", "warnings", "instances": [settings documents], "owner": {tag: info}}."""
    plan = to_v2(plan)
    problems, warnings = [], []
    if not NAME_RE.match(plan.get("dataset") or ""):
        problems.append("dataset must be PascalCase letters and digits, starting with a letter")
    insts = plan.get("instances") or []
    if not insts:
        problems.append("at least one instance is needed")
    names = [i.get("name") for i in insts]
    if len(set(names)) != len(names):
        problems.append("instance names must be different")
    owner, reports, settings = {}, [], []
    for ii, inst in enumerate(insts):
        plugin = inst.get("plugin")
        if plugin not in PLUGINS:
            problems.append(f"instance {ii + 1}: plugin must be one of {', '.join(PLUGINS)}")
            continue
        if not NAME_RE.match(inst.get("name") or ""):
            problems.append(f"instance {ii + 1}: name must be PascalCase letters and digits, starting with a letter")
        if plugin == "OPCUA":
            r, ps_, own, st = _opcua_instance(conn, plan, inst)
        else:
            r, ps_, own, st, ws = _broker_instance(conn, plan, inst, inputs or _broker_inputs(conn))
            warnings += [f"{inst.get('name')}: {w}" for w in ws]
        problems += [f"{inst.get('name')}: {p}" for p in ps_]
        for tag, info in own.items():
            if tag in owner and not info.get("optional"):
                problems.append(f"tag {tag} is written by both {owner[tag]['instanceName']} and {inst.get('name')}")
            owner.setdefault(tag, {**info, "instance": ii, "instanceName": inst.get("name")})
        reports.append(r)
        settings.append(st)
    required = [t for t, i in owner.items() if not i.get("optional")]
    report = {"ok": not problems, "problems": problems, "warnings": warnings, "dataset": plan.get("dataset"),
              "tagsPredicted": len(required), "instances": reports}
    return {"report": report, "problems": problems, "warnings": warnings, "instances": settings, "owner": owner}


def _opcua_instance(conn, plan, inst):
    if conn.kind != "opcua":
        return {"instance": inst.get("name"), "plugin": "OPCUA"}, ["the OPCUA plugin needs an OPC UA server"], {}, None
    v1 = {"name": inst.get("name"), "dataset": plan.get("dataset"), "subscriptions": inst.get("subscriptions") or [], "notes": inst.get("notes") or []}
    report, problems = validate_collector(conn, v1)
    own = report.pop("_owner")
    by_tag = {n["path"].replace("/", "."): n for n in conn.nodes.values() if n["nodeClass"] == "Variable"}
    owner = {tag: {"subscription": i, "dataType": (by_tag.get(tag) or {}).get("dataType") or "?", "uom": units_of(by_tag.get(tag) or {}),
                   "source": {"tag": tag}} for tag, i in own.items()}
    st = collector_instance(conn, v1, report) if not problems else None
    report = {"instance": inst.get("name"), "plugin": "OPCUA", **report}
    return report, [p for p in problems if not p.startswith("dataset")], owner, st


def _broker_inputs(conn):
    import adapters.mqtt as am
    return am.planning_inputs(conn)


def _broker_instance(conn, plan, inst, inp):
    name, plugin = inst.get("name"), inst.get("plugin")
    problems, warnings, owner, reps = [], [], {}, []
    if conn.kind != "mqtt":
        return {"instance": name, "plugin": plugin}, [f"the {plugin} plugin needs an MQTT broker"], {}, None, []
    shapes, cache, births = inp["shapes"], inp["cache"], inp["births"]
    subs_out = []
    for si, sub in enumerate(inst.get("subscriptions") or []):
        topics = _lines(sub.get("topics"))
        rep = {"subscription": si + 1, "topics": {}}
        if not topics:
            problems.append(f"subscription {si + 1} has no topics")
        for t in topics:
            if "#" in t[:-1] or ("#" in t and not (t == "#" or t.endswith("/#"))):
                problems.append(f"topic '{t}': '#' may only be the last level")
            if "." in t and "/" not in t and t.count(".") >= 2:
                warnings.append(f"topic '{t}' looks dot-delimited; MQTT topics are slash-delimited")
            spb_topic = t.startswith("spBv1.0")
            if plugin == "MQTT" and spb_topic:
                problems.append(f"topic '{t}' is Sparkplug B: plan it on a SparkplugB instance")
            if plugin == "SparkplugB" and not spb_topic:
                problems.append(f"topic '{t}' is not Sparkplug B (spBv1.0/...): plan it on an MQTT instance")
            hits = [x for x in inp["excluded"] if ps.topic_filter_match(t, x)]
            if hits and not any(ps.topic_filter_match(t, x) for x in shapes):
                problems.append(f"topic '{t}' only matches topics that are not for Handoffs (e.g. {hits[0]})")
            meta = [x for x in inp["metadata"] if ps.topic_filter_match(t, x)]
            if meta:
                warnings.append(f"topic '{t}' also matches {len(meta)} metadata topics; Collector would log them too, so narrow the topic")
        rx, rx_problem, rx_warn = cn.check_regex(sub.get("excludeRegex"))
        if rx_problem:
            problems.append(f"subscription {si + 1}: {rx_problem}")
        warnings += [f"subscription {si + 1}: {w}" for w in rx_warn]
        preds = []
        if plugin == "SparkplugB":
            st = spb_subscription(sub)
            preds = cn.sparkplug(st, births, rx)
            if not births:
                warnings.append(f"subscription {si + 1}: no Sparkplug B birth seen yet, so its tags cannot be predicted")
            rep["topics"] = {t: sum(1 for g, n, d, _ in births if ps.topic_filter_match(t, f"spBv1.0/{g}/{'DBIRTH' if d else 'NBIRTH'}/{n}" + (f"/{d}" if d else ""))) for t in topics}
        else:
            st, shape = mqtt_subscription(sub, shapes)
            matched = sorted(x for x in shapes if ps.any_match(topics, x))
            rep["topics"] = {t: sum(1 for x in shapes if ps.topic_filter_match(t, x)) for t in topics}
            kinds = defaultdict(int)
            for x in matched:
                kinds[shapes[x]["shape"]] += 1
            if len(kinds) > 1:
                warnings.append(f"subscription {si + 1} matches topics of different shapes {dict(kinds)}; one Type may not fit all")
            if kinds.get("Unsupported"):
                problems.append(f"subscription {si + 1} matches {kinds['Unsupported']} topics Collector cannot log (not JSON or a single value)")
            fit = {"Simple": "Simple", "JsonValueObject": "JsonStructured", "JsonMetricsArray": "JsonStructured", "JsonRecord": "JsonSimple"}
            if shape and fit.get(shape) and st["Type"] != fit[shape]:
                problems.append(f"subscription {si + 1}: Type {st['Type']} does not fit its payloads ({shape}); use {fit[shape]}")
            keys = [k for k in (st.get("TopicDefinition") or "").split("/") if k]
            for f, v in st["Fields"].items():
                for k in re.findall(r"\[Topic:([^\]]+)\]", v):
                    if k not in keys:
                        problems.append(f"field {f} uses [Topic:{k}] but the topic definition has no '{k}' level")
            if st.get("TopicDefinition") and "." in st["TopicDefinition"] and "/" not in st["TopicDefinition"]:
                problems.append(f"subscription {si + 1}: the MQTT topic definition is slash-delimited (e.g. plant/area/equipment)")
            for x in matched:
                if shapes[x]["shape"] == "Unsupported":
                    continue
                e = cache.get(x) or {}
                obj = ps_json(e.get("p"))
                preds += cn.mqtt(st, x, e.get("p"), obj, rx)
            if matched and not preds:
                problems.append(f"subscription {si + 1} matches {len(matched)} topics but predicts no tags with these settings")
        for t, n in rep["topics"].items():
            if n == 0:
                problems.append(f"topic '{t}' matches no {'Sparkplug B Edge Node' if plugin == 'SparkplugB' else 'plannable topic'} on this broker")
        counts = defaultdict(list)
        for p in preds:
            counts[p["tag"]].append(p)
        coll = [{"tag": t, "from": [ps_where(x) for x in v][:4]} for t, v in counts.items() if len(v) > 1 and not v[0].get("optional")]
        if coll:
            problems.append(f"subscription {si + 1}: {len(coll)} tag names collide (e.g. {coll[0]['tag']} from {', '.join(coll[0]['from'])}); "
                            "JSON Simple drops array keys and indexes, so use TagnameFields, a JSON Structured subscription, or exclude them")
        for p in preds:
            if p["tag"] in owner and not p.get("optional") and owner[p["tag"]]["subscription"] != si:
                problems.append(f"tag {p['tag']} is written by subscriptions {owner[p['tag']]['subscription'] + 1} and {si + 1}")
                break
        for p in preds:
            owner.setdefault(p["tag"], {"subscription": si, "dataType": p["dataType"], "uom": p["uom"], "fields": p["fields"],
                                        "source": p["source"], **({"optional": True} if p.get("optional") else {})})
        rep.update({"predictedTags": sum(1 for p in preds if not p.get("optional")), "collisions": coll[:5],
                    "sampleTags": [p["tag"] for p in preds if not p.get("optional")][:8], "settings": st})
        reps.append(rep)
        subs_out.append(st)
    conn_settings, needs_pw, notes = broker_connection(conn.rec)
    settings = {"name": name, "type": plugin, "description": f"{conn.rec['name']} ({conn.status().get('endpoint')}) - planned by Witness",
                "historian": {"dataset": plan.get("dataset")}, "Settings": {**conn_settings, "Subscriptions": subs_out},
                "needsPassword": needs_pw, "connectionNotes": notes, "notes": inst.get("notes") or [],
                "tagsPredicted": sum(r["predictedTags"] for r in reps)}
    report = {"instance": name, "plugin": plugin, "subscriptions": reps, "tagsPredicted": settings["tagsPredicted"]}
    return report, problems, owner, settings, warnings


def ps_json(text):
    import json
    try:
        v = json.loads(text) if text else None
        return v if isinstance(v, (dict, list)) else None
    except ValueError:
        return None


def ps_where(p):
    s = p.get("source") or {}
    return s.get("jsonPath") or s.get("element") or s.get("metric") or s.get("topic") or "?"
