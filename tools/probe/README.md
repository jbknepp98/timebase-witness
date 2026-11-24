# Probe harness

The probe harness is a throwaway MQTT broker plus a publisher that sends every payload shape Timebase Collector can log:

- Simple (primitives);
- JSON (Simple);
- JSON (Structured), both as a value object per topic and as a metrics array;
- Sparkplug B, with births, aliases, nested templates, DataSet, arrays and DateTime.

The publisher also sends a metadata tree, a Bridge-shaped topic and a non-JSON topic. Running a test Collector against it shows exactly which tags Collector writes, and Handoffs' tag-name predictions are tested against that output.

| File | What it is |
|---|---|
| `probe_pub.py` | Fixture publisher (see its docstring) |
| `docker-compose.yml` | The broker and publisher, on the Timebase Docker network |
| `mosquitto.conf` | Anonymous broker, port 1883, no persistence |
| `collector-settings.json` | Collector instances that log every fixture |
| `fixtures.json` | One recorded round of every fixture message (Sparkplug as base64), for unit tests |
| `expected-tags.json` | What Collector actually wrote for `collector-settings.json`: names, types, units, fields |
| `naming-findings.md` | Collector's tag naming rules, as observed |

The broker is anonymous and lives only on the Docker network, so the harness needs no passwords. Never point it at a shared broker.

## Run it on the Timebase host

```bash
scp tools/probe/* mac-mini:witness-probe/
ssh mac-mini 'cd ~/witness-probe && docker compose up -d'
```

Check that it publishes:

```bash
ssh mac-mini 'docker exec witness-probe-broker mosquitto_sub -t "probe/#" -C 20 -W 5 -v'
```

Stop it when you're done:

```bash
ssh mac-mini 'cd ~/witness-probe && docker compose down'
```

The publisher runs for an hour (`DURATION`). It sends Sparkplug births every 2 minutes, and whenever a host asks for a rebirth.

## Record fixtures

```bash
python3 tools/probe/probe_pub.py --dry --record tools/probe/fixtures.json
```

`--dry` encodes one round without a broker, so paho isn't needed. Timestamps are taken from when the command runs.

## Test Collector instances

The Collector MCP connector is read-only, so create the instances through Collector's web API, from a browser tab signed in to Collector (`https://<host>:4522`). Paste `collector-settings.json` as `cfg` and run this in the tab's console:

```js
const J = {'Content-Type': 'application/json'}; const wait = (ms) => new Promise(r => setTimeout(r, ms));
for (const i of cfg.instances) {
  if (!i.name.startsWith('WitnessProbe')) throw new Error('only WitnessProbe* instances');
  const c = await (await fetch('/app/collectors', {method: 'POST', headers: J, body: JSON.stringify({type: i.type, name: i.name})})).json();
  await fetch(`/app/collectors/${c.id}/settings`, {method: 'PUT', headers: J, body: JSON.stringify({Settings: i.Settings})});
  await fetch(`/app/collectors/${c.id}/historians`, {method: 'PUT', headers: J, body: JSON.stringify({historians: [{id: '<historian id>', dataset: i.dataset}]})});
  // settings apply only after the instance is switched off and on again
  for (const a of [true, false, true]) { await fetch(`/app/collectors/${c.id}/active`, {method: 'PATCH', headers: J, body: JSON.stringify({active: a})}); await wait(1500); }
}
```

Read the result with the Collector preview (`GetPreviewSnapshot`) or Historian (`GetTags` on the dataset).

Remove the instances afterwards:

```js
const all = await (await fetch('/app/collectors')).json();
for (const p of (all.items || all).filter(x => x.name.startsWith('WitnessProbe'))) {
  await fetch(`/app/collectors/${p.id}/active`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({active: false})});
  await new Promise(r => setTimeout(r, 2000));
  await fetch(`/app/collectors/${p.id}`, {method: 'DELETE'});
}
```

Only create or remove instances and datasets named `WitnessProbe*`. The datasets stay in Historian after the instances are removed.

## Update the golden files

`expected-tags.json` must come from a real run, never from expectations.

1. Start the stack and create the instances.
2. Wait for a Sparkplug birth.
3. Copy the user tags from `GetTags` for each dataset.
4. Record anything new in `naming-findings.md`.
