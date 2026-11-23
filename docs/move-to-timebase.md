# Move to Timebase

**Move to Timebase** (`#/atlas`, under *Build* in the left menu) turns a live OPC UA server into two handoffs for Gage. One sets up logging in Collector; the other models the plant in Atlas.

## Running it

1. Pick the server in the **Namespace** dropdown.
2. Start the run. Progress streams in as the agent works. A run takes about 90 seconds and uses roughly 20k input and 11k output tokens.
3. When it finishes, use the dropdown at the top of the result to switch between the **Atlas** and **Collector** handoffs. Each handoff card has a **Copy Gage prompt** button and download buttons.

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

## The two handoffs

Each run saves numbered versions in `briefs/`, plus a "latest" copy of each.

### Collector handoff

The files are `<domain>-collector-vN.md` and `<domain>-collector-vN.json`. The handoff describes an **OPCUA** collector instance that logs the server to a Historian dataset:

- the instance name and dataset;
- URL, user name and security policy and mode;
- subscriptions with topics (dot-delimited browse paths, `+` and `#` wildcards), topic definition, interval, exclusion filter and fields.

`AutoAcceptUntrusted` is on unless the connection pins a server certificate. **The password is never included.** Gage in Collector asks for it.

The Collector container has no curl or Python, so **Copy Gage prompt** puts the whole handoff into the prompt.

### Atlas handoff

The file is `<domain>-vN.md`. It contains:

- a preface that tells Gage to run model-domain in Build mode and skip the interview;
- a **Domain Summary** in Gage's own format;
- source bindings for Gage's mapper, in the form `{CONNECTOR}/<dot-joined browse path>`;
- the prerequisites outside Atlas, such as the Connect connector.

Gage in Atlas fetches the handoff by URL, from `http://lookout-gateway:8090/briefs/<file>` over the Timebase Docker network.

## Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | | Required for Move to Timebase |
| `LOOKOUT_AGENT_MODEL` | `claude-opus-5-5` | Model for the agent |
| `LOOKOUT_AGENT_EFFORT` | `high` | Reasoning effort |
| `LOOKOUT_AGENT_MAX_TURNS` | `12` | Tool-loop limit |
| `LOOKOUT_INTERNAL_URL` | `http://lookout-gateway:8090` | Base URL that Gage uses to fetch handoffs |
| `BRIEF_DIR` | `/data/briefs` | Where handoffs are saved |
