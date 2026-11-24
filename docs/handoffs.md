# Handoffs

The **Handoffs** page (`#/atlas`, under *Build* in the left menu) turns a live source into three handoffs for Gage, one for each step of the data path. The source can be:

- an **OPC UA server**;
- an **MQTT broker**, including Sparkplug B on that broker.

```
source ──▶ Collector ──▶ Historian dataset ──▶ Connect (Historian connector) ──▶ Atlas
```

1. **Collector** historizes the source into one Historian dataset. This can take one Collector instance or several:
   - OPCUA for a server;
   - MQTT for plain topics;
   - SparkplugB for `spBv1.0/...`.
2. **Connect** serves that dataset to Atlas through a Timebase.Historian connector.
3. **Atlas** models the plant, binding every property through the Connect connector.

Run them in that order: each step needs the one before it.

## Running it

1. Pick the source in the dropdown. OPC UA servers and MQTT brokers are listed separately. A broker's entry says "MQTT · Sparkplug" once Witness has seen Sparkplug B on it.
2. Name the domain, then select **Plan the move** (or **Plan again**).
3. While the agent works, the panel shows **Agent activity** at full width.
4. When the run finishes, the panel turns to **Handoffs**:
   - Select the **Collector**, **Connect** or **Atlas** card to show that handoff below; the selected card has a Timebase Blue border.
   - Each card has **Copy Gage prompt** and download buttons.
   - The **Version** dropdown picks a saved version.
   - The pager in the panel header (‹ 1 / 2 ›) goes back to the activity.

A run takes 1 to 2 minutes. Before you run it, let the gateway watch the source for a few minutes: the agent uses the observed state lists and value ranges, and these reset when the gateway restarts.

## What the agent sees

The gateway turns every source into the same **source model**: objects and signals, with data types, units, live values, what Witness has observed, and hints.

| Source | Objects | Signals |
| --- | --- | --- |
| OPC UA | OPC UA Objects | Variables |
| MQTT, one value per topic | the topic's levels | the topic |
| MQTT, JSON record | the topic | each JSON leaf |
| MQTT, JSON metrics array | the topic | each array element |
| Sparkplug B | group, Edge Node, device, template instances, metric folders | metrics and template members |

### Payload shapes

For every MQTT topic, Witness detects the payload shape and the Collector settings it needs:

| Shape | Example | Collector subscription |
| --- | --- | --- |
| Simple | `72.5`, `true`, `Running` | Type Simple |
| JSON value object | `{"value": 8.3, "timestamp": "…", "quality": 192, "units": "bar"}` | Type JSON Structured, with Value, Quality, UOM and Timestamp fields |
| JSON metrics array | `{"metrics": [{"name": "Tag 1", "value": 1}, …]}` | Type JSON Structured, with Tagname Fields set to the name |
| JSON record | `{"Level": {"Value": 50}, "Manufacturer": "Acme"}` | Type JSON Simple |
| Sparkplug B | protobuf on `spBv1.0/...` | the SparkplugB plugin |
| Unsupported | CSV, other binary | cannot be logged; the agent lists it as an open question |

Topics that one subscription could cover are grouped together. The groups are listed in the profile.

### What is left out

- **"Not for Handoffs" topics.** Each broker connection has this list in its settings, `$SYS/#` by default. See [Connections and security](connections-and-security.md#not-for-handoffs).
- **What Timebase Bridge publishes.** Logging it would loop Timebase's own output back into Historian.
- **Metadata topics.** These describe other topics. They are used as hints and never planned for logging.

Live and Namespace still show all of these topics.

### Hints

Sources often describe their signals somewhere other than in the message that carries the value. Witness collects these descriptions and attaches them to the right objects and signals:

| Hint | Where it comes from |
| --- | --- |
| OPC UA TypeDefinitions | Each object's type, plus the variables and properties the type declares |
| Sparkplug B templates | Template definitions from the births: members, units (`engUnit`), version, parameters. Instances count too, nested ones included |
| Metadata topics | Topics that mirror the data topics, for example `_meta/<topic>` from the OPC UA to MQTT mirror. They carry `typeDefinition`, `dataType`, `units`, `description` and static `properties`, plus a `_types/<Type>` catalog. Witness finds the metadata level itself, and uses a `valueTopic` link when there is one |
| JSON keys | Units and data types carried in the value payload |

When sources disagree, the most specific one wins: Sparkplug, then OPC UA, then the metadata topic, then JSON keys. The disagreement is kept in the hint.

The agent treats declared types as the strongest evidence for entity types. For example, `AirCompressorType` becomes the entity type `AirCompressor`, with the type's members as properties.

### Tools

The gateway runs a Claude agent loop (default model `claude-opus-5-5`) with these tools. None of them writes anything.

| Tool | Purpose |
| --- | --- |
| `get_namespace_profile` | Identity and security, object tree, repeated patterns, types and hints. For brokers also topic groups, unsupported topics and exclusions |
| `inspect_branch` | Signals under an object, with types, units, descriptions, observed values, hints and binding paths |
| `get_atlas_vocabulary` | The Atlas terms and type kinds that the summary should use |
| `propose_collector_instance` | The agent's Collector plan, which Witness checks (see below) |

To see what the tools return without calling the model, use `GET /api/agent/profile?server=<id>[&path=<object>]`. `POST /api/agent/validate` checks a plan the same way, also without the model.

## The Collector plan

The agent proposes a dataset and one or more instances, each with a plugin (`OPCUA`, `MQTT` or `SparkplugB`) and subscriptions. Witness then does three things:

- **Fills in** the payload settings the agent left out, using the detected shapes. With them, a subscription can be as short as `{"topics": ["Northbeam/#"]}`.
- **Predicts every tag** the plan will write: the name, data type, unit and fields, using Collector's naming rules (below).
- **Reports problems:**
  - topics that match nothing;
  - a Type that does not fit the payloads;
  - JSON Simple array collisions;
  - two subscriptions or instances writing the same tag;
  - "Not for Handoffs" or metadata topics in the plan;
  - Sparkplug topics on an MQTT instance (or the reverse);
  - unsupported topics;
  - an invalid exclusion filter.

  The agent fixes the problems and proposes again.

  Witness also warns about regex constructs that .NET reads differently from Python.

Once a plan passes, the inspect results and the binding examples use the predicted tag names. Signals the plan doesn't log have no binding.

### How Collector names tags

These rules were checked against a real Collector with the probe harness (`tools/probe/`). Witness's predictions reproduce its output exactly.

| Plugin and type | Tag name | Example |
| --- | --- | --- |
| OPCUA | The browse path under Objects, joined with dots | `DemoPlant.Processing.MixTank101.LevelPct` |
| MQTT Simple | The topic, with `/` replaced by the delimiter (Witness uses `.`) | `probe.simple.Line1.Motor1.Temp` |
| MQTT JSON Structured, value object | The topic, minus Ignore Parts (which apply to the delimited name) | `DemoPlant.Utilities.Boiler.SteamPressureBar`, unit `bar` |
| MQTT JSON Structured, metrics array | Built from Tagname Fields, read on each element | `Tag 1` |
| MQTT JSON Simple | The topic, then the JSON keys. Timestamp fields are left out | `…MX-101.Level.Value` |
| SparkplugB | `Group/Node[/Device]/<metric>`, keeping the metric's folders; template members are `<instance>.<member>` | `ProbeGroup/Gateway1/Filler01/Pump1.Motor.Speed` |

Some rules to know:

- **JSON Simple drops both an array's key and its index.** `Orders[0].Id` and `Orders[1].Id` both become `…Id`, so their values collide. Witness reports this, and the agent excludes the array or plans those topics another way.
- **JSON numbers are stored as Double.** Sparkplug keeps its own integer types. DateTime, DataSet and array values are stored as strings.
- **SparkplugB sets fields automatically:** GroupID, NodeID and DeviceID; for template members also TemplateInstance, TemplateMember, TemplateRef, TemplateRootInstance, TemplateRootRef, TemplateVersion and TemplateParam.\<name\>.
- **Sparkplug B leaves some metrics out:** template definitions and transient metrics produce no tags.
- **Rebirth requests may appear as a tag.** When Collector has to ask an Edge Node for a rebirth, it also logs that request (`Group/NCMD/Node/Node Control/Rebirth`).

## The three handoffs

Each run saves numbered versions in `briefs/`, plus a "latest" copy of each.

### Collector handoff

The files are `<domain>-collector-vN.md` and `<domain>-collector-vN.json`.

- **The Markdown** has a summary table of the instances, then a section for each with steps for Gage's setup-collector skill and the settings.
- **The JSON** is `{"dataset", "instances": [{"name", "type", "dataset", "Settings"}]}`.

Connection settings come from the Witness connection:

| Plugin | Connection settings |
| --- | --- |
| OPCUA | URL, user, security policy and mode |
| MQTT and SparkplugB | Host, Port, Use TLS and user name |

**The password is never included.** Gage in Collector asks for it.

The broker section also notes what Collector must do to connect:
- trust the broker's custom CA, if Witness uses one;
- use its own client certificate, if Witness uses one;
- use the TCP port if Witness connects over WebSockets;
- check the host name it reaches the broker by.

`AutoAcceptUntrusted` for OPC UA is on unless the connection pins a server certificate.

The Collector container has no curl or Python, so **Copy Gage prompt** puts the whole handoff into the prompt.

### Connect handoff

The files are `<domain>-connect-vN.md` and `<domain>-connect-vN.json`. Witness writes this handoff from the checked plan; the agent doesn't write it. It describes:

- **the connector:** a Timebase.Historian connector for the dataset, with the Historian host, port and TLS, sign-in as the Connect host, and one dataset entry. No secrets are needed. If a Historian connector already exists, Gage adds the dataset to it instead of creating another;
- **the tag naming rule** for each instance, with an example;
- **the fields** for each instance and subscription (Sparkplug B's automatic fields included);
- **the data types and units;**
- **sample tags** for each group of objects that log the same signals, labelled with their type.

The JSON also carries `predictedTags`, the full list of tags the dataset will hold.

The per-tag binding path is `<connector id>/<dataset>/<tag name>`. Atlas's connector catalog gives Historian connectors the template `<connector>/<Dataset>/[Tag:path]`. A `path` parameter takes tag names containing `/` (Sparkplug B) exactly as they are.

The handoff asks Gage to report the connector id, which the Atlas handoff needs.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CONNECT_HISTORIAN_HOST` | `historian` | Historian host as Connect reaches it |
| `CONNECT_HISTORIAN_PORT` | `4512` | Historian port |
| `CONNECT_HISTORIAN_TLS` | `true` | Whether Connect uses TLS to reach Historian |

### Atlas handoff

The file is `<domain>-vN.md`. It contains:

- a preface that tells Gage to run model-domain in Build mode and skip the interview;
- a **Domain Summary** in Gage's own format;
- source bindings for Gage's mapper, in the form `{CONNECTOR}/<dataset>/<tag name>`, using the predicted tag names. Witness fills in the dataset; `{CONNECTOR}` is the id of the Historian connector from the Connect handoff;
- the prerequisites outside Atlas: the Collector instances and the Connect connector.

Gage in Atlas fetches the handoff by URL, from `http://lookout-gateway:8090/briefs/<file>` over the Timebase Docker network.

## Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | | Required for Handoffs |
| `LOOKOUT_AGENT_MODEL` | `claude-opus-5-5` | Model for the agent |
| `LOOKOUT_AGENT_EFFORT` | `high` | Reasoning effort |
| `LOOKOUT_AGENT_MAX_TURNS` | `12` | Tool-loop limit |
| `LOOKOUT_INTERNAL_URL` | `http://lookout-gateway:8090` | Base URL that Gage uses to fetch handoffs |
| `BRIEF_DIR` | `/data/briefs` | Where handoffs are saved |
| `MQTT_STATS_MAX` | `100000` | How many MQTT values (topics, JSON leaves, Sparkplug metrics) the gateway observes |

The Bridge lookup variables are in [Connections and security](connections-and-security.md#not-for-handoffs).

## Cost

| Source | Turns | Output tokens | Cache read | Cache write |
| --- | --- | --- | --- | --- |
| OPC UA server with about 1,000 variables | 5 | 28k | 230k | 100k |
| Broker mirroring the same plant | 4 | 24k | 120k | 70k |
| Small mixed MQTT and Sparkplug B broker | 5 | 17k | 80k | 40k |

Most input is read from the prompt cache.
