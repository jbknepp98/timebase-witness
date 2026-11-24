# How Timebase Collector names tags

These are findings from probe runs against Timebase Collector 2.0.861 on 2026-11-24. The runs used the fixtures in `probe_pub.py` and the settings in `collector-settings.json`. `expected-tags.json` is the exact output: names, data types, units and fields.

The docs ([MQTT](https://docs.timebase.com/#configuring-the-mqtt-data-collector), [Sparkplug B](https://docs.timebase.com/#configuring-the-mqtt-sparkplugb-collector)) describe the settings. The rules below are what Collector actually did, including the cases the docs leave open.

## MQTT plugin

### Simple (primitives)

- **Tag name:** the topic, with `/` replaced by `TagnameDelimiter` (default `/`). For example, `probe/simple/Line1/Motor1/Temp` becomes `probe.simple.Line1.Motor1.Temp`.
- **Data type:** read from the text. A number becomes Double, `true`/`false` becomes Boolean, anything else String.

### JSON (Simple)

- **Tag name:** the topic plus the flattened key path, joined with the delimiter, when `TagnameIncludesTopic` is on.
- **Dropped keys:** keys listed in `TimestampFields` are not tags (`payload.timestamp`, `emitTime`, `ts`). Timestamp-like keys that aren't listed stay tags, for example `Level.Timestamp`, which is stored as a String.
- **Arrays drop both the array key and the index:**
  - `{"data":[{"motor2":{"rpm":1}}]}` becomes `….motor2.rpm`.
  - `{"Orders":[{"Id":"MO-1","Hours":2.5},{"Id":"MO-2","Hours":1}]}` becomes `….Id` and `….Hours`. These **collide**: each message writes two values to the same tag.
- **Data types:**
  - integers are stored as Double (`cycleCount`, `Level.Quality`);
  - booleans as Boolean;
  - strings as String.
- **Units:** a nested value object is just a record here. `{"pressure":{"value":4.2,"units":"bar"}}` gives two tags, `pressure.value` (Double) and `pressure.units` (String), and **no unit** on the value. Use JSON (Structured) to get units.
- **`[Payload:path]` fields:** resolved per message, and empty when the key is missing (`Uri=` on topics without `instanceUri`).

### JSON (Structured), one value object per topic

This uses `ValueField value`, `QualityField quality`, `UOMFields ["units"]`, `TimestampFields ["timestamp"]` and `TimestampType String`.

- **Tag name:** the topic, delimited.
- **`IgnoreParts`:** matched against the **delimited** name (`probe.structured.`), not the slash topic. With that, `probe/structured/DemoPlant/Utilities/Boiler/SteamPressureBar` becomes `DemoPlant.Utilities.Boiler.SteamPressureBar`.
- **Units and types:** the uom comes from `units` (`bar`). String values stay String.

### JSON (Structured), metrics array

This is `payload.metrics[]`, with `TagnameIncludesTopic false`, `TagnameFields ["name"]` and `ValueField value`.

- **Paths are relative to each array element:**
  - the tag is the element's `name` (`Tag 1`);
  - the uom comes from the element's `uom` (`kW`);
  - the quality comes from `properties.Quality.value`.
- **Data types:** Int32 values are stored as Double, booleans as Boolean.

### Topic Definition and fields

`TopicDefinition` is slash-delimited. `[Topic:key]` resolves for each segment, and segments beyond the definition are ignored.

## SparkplugB plugin

The plugin has no Fields or TopicDefinition settings; Collector sets the fields itself.

### Tag names

- **Node metrics:** `Group/Node/<metric>`, for example `ProbeGroup/Gateway1/Uptime`.
- **Device metrics:** `Group/Node/Device/<metric>`. Folders in metric names keep `/`, for example `…/Filler01/Line/Speed` and `…/Gateway1/Diagnostics/CPU`.
- **Template members:**
  - `<instance>.<member>`, for example `…/Filler01/Motor1.Speed` and `Motor1.Status/Code`;
  - **nested:** `<instance>.<member instance>.<member>`, for example `…/Filler01/Pump1.Motor.Speed`.
- **Template definitions** (`_types_/Motor`, `_types_/Pump`) produce no tags.
- **Transient metrics** are dropped by default (`Scratch`).

### Housekeeping

With housekeeping on (the default), Collector keeps:
- `bdSeq`;
- `Node Control/Rebirth`;
- `Group/NCMD/Node/Node Control/Rebirth`, which appears when Collector itself asked for a rebirth. It may or may not be present.

### Fields

- **Automatic fields:** `GroupID`, `NodeID` and `DeviceID` (device metrics only). Command tags also get `Command=NCMD`.
- **Template members** also get these fields:
  - `TemplateInstance`: `Motor1`, or `Pump1.Motor` when nested;
  - `TemplateMember`: `Speed`, `Status/Code`;
  - `TemplateRef`: the member's own template, `Motor`;
  - `TemplateRootInstance` and `TemplateRootRef`: the outermost instance and its template, `Pump1` and `Pump`;
  - `TemplateVersion`: the member's own template version;
  - `TemplateParam.<name>`: the instance's value. When the instance gives none, the definition's default is used (`Pump1.Motor` gets `Rated=5kW` from the `Motor` definition).

### Data types and units

| Sparkplug type | Stored as |
|---|---|
| Int32 | Int32 |
| Int64 | Int64 |
| Float | Double (21.5 is kept as 21.5) |
| Double | Double |
| Boolean | Boolean |
| String | String |
| DateTime | String, ISO 8601 with milliseconds (`2026-11-24T00:23:50.661Z`) |
| DataSet | String, JSON `{"columns":[…],"types":["Int32","Double","String"],"rows":[[1,72.5,"Heat"],…]}` |
| Int32Array | String, a JSON list (`[1,0,1,1]`) |

Units come from the `engUnit` property, including on template members, where it comes from the member, or from the definition when the instance leaves it out.

### Sessions

Data that arrives before a birth is dropped, and Collector publishes an NCMD `Node Control/Rebirth`. `probe_pub.py` answers that request with a new birth.

## Collector web API (signed-in browser session)

| Call | What it does |
|---|---|
| `POST /app/collectors {type, name}` | Creates an instance and returns its `id` |
| `PUT /app/collectors/{id}/settings {Settings: {...}}` | Replaces the settings. They only apply after the instance is switched off and on again |
| `PUT /app/collectors/{id}/historians {historians: [{id, dataset}]}` | Sets the historian links |
| `PATCH /app/collectors/{id}/active {active}` | Switches the instance on or off |
| `DELETE /app/collectors/{id}` | Deletes the instance. Stop it first |
