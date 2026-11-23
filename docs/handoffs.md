# Handoffs

The **Handoffs** page (`#/atlas`, under *Build* in the left menu) turns a live OPC UA server into three handoffs for Gage, one for each step of the data path:

```
OPC UA server ──▶ Collector ──▶ Historian dataset ──▶ Connect (Historian connector) ──▶ Atlas
```

1. **Collector** historizes the server into a Historian dataset.
2. **Connect** serves that dataset to Atlas through a Timebase.Historian connector.
3. **Atlas** models the plant, binding every property through the Connect connector.

Run them in that order: each step needs the one before it.

## Running it

1. Pick the server in the **Namespace** dropdown.
2. Start the run. Progress streams in as the agent works. A run takes about 90 seconds and uses roughly 20k input and 11k output tokens.
3. When it finishes, select the **Collector**, **Connect** or **Atlas** card to show that handoff below. The selected card has a Timebase Blue border. Each card has its own **Copy Gage prompt** button, with its download buttons on the row below. The **Version** dropdown on the right picks a saved version.

Let the gateway watch the server for a few minutes before running. The agent relies on the observed state lists and value ranges, and these reset when the gateway restarts.

## What the agent does

The gateway runs a Claude agent loop (default model `claude-opus-5-5`). The agent has these read-only tools:

| Tool | Purpose |
| --- | --- |
| `get_namespace_profile` | Server identity, security, browse roots, and object and variable counts |
| `inspect_branch` | Variables under a branch, with types, units, descriptions and observed values |
| `get_atlas_vocabulary` | The Atlas terms and type kinds that the summary should use |
| `propose_collector_instance` | The agent's plan for the Collector instance, checked by Witness |

Witness checks the agent's Collector plan against the live namespace. It counts matched, excluded and logged variables, flags problems, and fills in the URL, user and security from the connection itself. If the agent finishes without proposing a Collector instance, Witness asks it once more.

To see what the tools return without calling the model, use `GET /api/agent/profile?server=<id>[&path=<object>]`.

## The three handoffs

Each run saves numbered versions in `briefs/`, plus a "latest" copy of each.

### Collector handoff

The files are `<domain>-collector-vN.md` and `<domain>-collector-vN.json`. The handoff describes an **OPCUA** collector instance that logs the server to a Historian dataset:

- the instance name and dataset;
- URL, user name and security policy and mode;
- subscriptions with topics (dot-delimited browse paths, `+` and `#` wildcards), topic definition, interval, exclusion filter and fields.

`AutoAcceptUntrusted` is on unless the connection pins a server certificate. **The password is never included.** Gage in Collector asks for it.

The Collector container has no curl or Python, so **Copy Gage prompt** puts the whole handoff into the prompt.

### Connect handoff

The files are `<domain>-connect-vN.md` and `<domain>-connect-vN.json`. Witness writes this one itself from the checked Collector plan; the agent is not involved. It describes:

- a **Timebase.Historian** connector that reads the Collector's dataset: Historian host, port and TLS, sign-in as the Connect host, and one dataset entry. No secrets are needed;
- **what the dataset looks like**: tag names (the dot-joined browse path, e.g. `DemoPlant.Processing.MixTank101.LevelPct`), the fields Collector writes on each tag, listed per Collector subscription since each has its own topic definition (e.g. Plant, Area, Equipment), with their values, data types, units, and sample tags for each group of objects that log the same signals;
- the per-tag binding path through the connector, `<connector id>/<dataset>/<tag name>`.

If a Historian connector already exists, Gage adds the dataset to it instead of creating another. The handoff asks Gage to report the connector id, which the Atlas handoff needs.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CONNECT_HISTORIAN_HOST` | `historian` | Historian host as Connect reaches it |
| `CONNECT_HISTORIAN_PORT` | `4512` | Historian port |
| `CONNECT_HISTORIAN_TLS` | `true` | Whether Connect uses TLS to reach Historian |

### Atlas handoff

The file is `<domain>-vN.md`. It contains:

- a preface that tells Gage to run model-domain in Build mode and skip the interview;
- a **Domain Summary** in Gage's own format;
- source bindings for Gage's mapper, in the form `{CONNECTOR}/<dataset>/<tag name>`. Witness fills in the dataset; `{CONNECTOR}` is the id of the Historian connector from the Connect handoff;
- the prerequisites outside Atlas: the Collector instance and the Connect connector.

Only variables the Collector logs exist in Historian, so the agent does not bind properties to variables it excluded.

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
