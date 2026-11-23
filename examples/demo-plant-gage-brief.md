> **For Gage:** use the **model-domain** skill in **Build** mode for a new domain named `demo-plant`.
> The Domain Summary below was drafted by Witness from the live OPC UA server `opcua-sim` (opc.tcp://opcua-sim:4840) and reviewed by the user - treat it as the confirmed interview output and **skip Step 1**.
> Hand the Domain Summary to **architect**, then **builder**. For **mapper**, use the Source Bindings section. Every binding path starts with `con_d0a001`, the Connect OPC UA connector that already serves this server. Then run **reviewer** post-change.

# Domain Summary: demo-plant

## Overview
`opcua-sim` (Flow OPC UA Simulator 1.0.0, `opc.tcp://opcua-sim:4840`) exposes one demo beverage/dairy-style plant, **DemoPlant**. It has three functional areas:
- **Processing**: a mix tank and a pasteurizer.
- **Packaging**: a filler, a capper and a conveyor.
- **Utilities**: a boiler, an air compressor and the main electrical feed.

The namespace has 13 objects and 30 variables. Every equipment object is unique: no variable set repeats. The result is eight single-instance equipment types under one Site and three Areas. Each live variable becomes a TVQ property. Two of them are writable setpoints. A `Simulator` folder holds two diagnostic nodes (Heartbeat, Version). It is not plant equipment and is left out of the model.

Witness observed the server for **259 seconds (about 4 minutes)**. All state lists and value ranges below come only from that window. Most analog signals update about once per second.

## Entity Types (master data)

### MixTank (derived from isa95-equipment:Unit)
- **State**: TVQ{Value=xsd:string} - batch phase. Observed only `Filling` and `Mixing`, so the list may be incomplete. Enumeration candidate.
- **LevelPct**: TVQ{Value=xsd:double} - tank level, unit %. Observed 62.3–95.0.
- **TempSetpointC**: TVQ{Value=xsd:double} - **setpoint**, writable on the server ("Writable setpoint"), unit degC. Held at 20.0 while observed.
- **TemperatureC**: TVQ{Value=xsd:double} - product temperature, unit degC. Observed 19.76–20.62.
- **AgitatorRpm**: TVQ{Value=xsd:double} - agitator speed, unit rpm. Observed 0.0–123.2.
- **AgitatorRunning**: TVQ{Value=xsd:boolean} - agitator run status. Observed both true and false.
- **BatchCount**: TVQ{Value=xsd:double} - batch counter (Int32 on the server). Stayed at 1004 while observed.

### Pasteurizer (derived from isa95-equipment:Unit)
- **State**: TVQ{Value=xsd:string} - operating state. Observed only `Running`, so the list is incomplete. Enumeration candidate.
- **HoldTempSetpointC**: TVQ{Value=xsd:double} - **setpoint** for hold-tube temperature, writable on the server, unit degC. Held at 72.5 while observed.
- **HoldTempC**: TVQ{Value=xsd:double} - hold-tube temperature, unit degC. Observed 71.24–73.41.
- **FlowLpm**: TVQ{Value=xsd:double} - product flow, unit L/min. Observed 330.3–346.1.
- **TotalLiters**: TVQ{Value=xsd:double} - running volume total, unit L. Rose steadily (29558.3 → 31034.1).

### Filler (derived from isa95-equipment:WorkCell)
- **State**: TVQ{Value=xsd:string} - operating state. Observed only `Running`, so the list is incomplete. Enumeration candidate.
- **Running**: TVQ{Value=xsd:boolean} - run status. Observed only true.
- **SpeedBpm**: TVQ{Value=xsd:double} - filling speed, unit bottles/min. Observed 584.9–614.3.
- **GoodCount**: TVQ{Value=xsd:double} - good bottles counter (Int64 on the server). Rose steadily.
- **RejectCount**: TVQ{Value=xsd:double} - rejected bottles counter (Int64 on the server). Rose steadily.
- **FillVolumeMl**: TVQ{Value=xsd:double} - fill volume per bottle, unit mL. Observed 499.21–501.57.

### Capper (derived from isa95-equipment:WorkCell)
- **State**: TVQ{Value=xsd:string} - operating state. Observed only `Running`, so the list is incomplete. Enumeration candidate.
- **TorqueNm**: TVQ{Value=xsd:double} - capping torque, unit N.m. Observed 2.02–2.41.

### Conveyor (derived from isa95-equipment:WorkCell)
- **SpeedMps**: TVQ{Value=xsd:double} - belt speed, unit m/s. Observed 1.148–1.264.
- **MotorCurrentA**: TVQ{Value=xsd:double} - drive motor current, unit A. Observed 7.27–8.11.

### Boiler (derived from isa95-equipment:Unit)
- **SteamPressureBar**: TVQ{Value=xsd:double} - steam header pressure, unit bar. Observed 8.102–8.515.
- **StackTempC**: TVQ{Value=xsd:double} - flue stack temperature, unit degC. Observed 178.4–182.8.

### AirCompressor (derived from isa95-equipment:Unit)
- **PressureBar**: TVQ{Value=xsd:double} - compressed-air pressure, unit bar. Observed 6.669–7.214.
- **Running**: TVQ{Value=xsd:boolean} - run status. Observed only true.

### PowerMeter (derived from isa95-equipment:Unit)
- **DemandKw**: TVQ{Value=xsd:double} - plant electrical demand, unit kW. Observed 345.2–384.5.
- **EnergyKwh**: TVQ{Value=xsd:double} - cumulative energy total, unit kWh. Rose steadily.

## Data Types (transactional records)
None - every signal is a TVQ property

## Relationship Types

### siteContains (contains)
- Site --siteContains--> Area (reused from isa95-equipment as is: DemoPlant → Processing, Packaging, Utilities)

### areaContainsUnit (contains)
Narrows `isa95-equipment:equipmentContains`, because there is no WorkCenter level between the areas and their process equipment.
- Area --areaContainsUnit--> MixTank
- Area --areaContainsUnit--> Pasteurizer
- Area --areaContainsUnit--> Boiler
- Area --areaContainsUnit--> AirCompressor
- Area --areaContainsUnit--> PowerMeter

### areaContainsWorkCell (contains)
Narrows `isa95-equipment:equipmentContains`, because the server has no ProductionLine level between Packaging and its stations.
- Area --areaContainsWorkCell--> Filler
- Area --areaContainsWorkCell--> Capper
- Area --areaContainsWorkCell--> Conveyor

## Library Reuse Candidates
- `atlas-common:TVQ`: range of every live property, with Value pinned as listed above.
- `isa95-equipment:Site`: used directly for DemoPlant. The server has no site-level variables, so no derived type is needed.
- `isa95-equipment:Area`: used directly for Processing, Packaging and Utilities. They are functional groupings straight under the site with no variables, so they are Areas, not WorkCenters.
- `isa95-equipment:Unit`: base for MixTank, Pasteurizer, Boiler, AirCompressor and PowerMeter.
- `isa95-equipment:WorkCell`: base for Filler, Capper and Conveyor.
- `isa95-equipment:siteContains`: reused unchanged.
- `isa95-equipment:equipmentContains`: abstract parent of areaContainsUnit and areaContainsWorkCell.
- `atlas-common:Tag`, `atlas-common:Folder`: not used. Signals are TVQ properties on equipment, and the `Simulator` folder is left out.

## Instance Patterns

### Site
- isa95-equipment:Site: 1 instance (DemoPlant)

### Areas
- isa95-equipment:Area: 3 instances, told apart by browse name under DemoPlant (Processing, Packaging, Utilities)

### Processing
- MixTank: 1 instance, told apart by browse name (MixTank101)
- Pasteurizer: 1 instance, told apart by browse name (Pasteurizer201)

### Packaging
- Filler: 1 instance, told apart by browse name (Filler301)
- Capper: 1 instance, told apart by browse name (Capper302)
- Conveyor: 1 instance, told apart by browse name (Conveyor303)

### Utilities
- Boiler: 1 instance, told apart by browse name (Boiler)
- AirCompressor: 1 instance, told apart by browse name (AirCompressor)
- PowerMeter: 1 instance, told apart by browse name (MainPower)

## Hierarchies
- DemoPlant (Site)
  - --siteContains--> Processing (Area)
    - --areaContainsUnit--> MixTank101 (MixTank)
    - --areaContainsUnit--> Pasteurizer201 (Pasteurizer)
  - --siteContains--> Packaging (Area)
    - --areaContainsWorkCell--> Filler301 (Filler)
    - --areaContainsWorkCell--> Capper302 (Capper)
    - --areaContainsWorkCell--> Conveyor303 (Conveyor)
  - --siteContains--> Utilities (Area)
    - --areaContainsUnit--> Boiler (Boiler)
    - --areaContainsUnit--> AirCompressor (AirCompressor)
    - --areaContainsUnit--> MainPower (PowerMeter)

## Open Questions
1. **Is Packaging one production line?** Filler301 → Capper302 → Conveyor303 looks like a bottling line. If it is, a `ProductionLine` under Packaging (with `areaContains` + `productionLineContains`) would fit ISA-95 better than `areaContainsWorkCell`. The namespace has no line object, so none was invented.
2. **State enumerations.** In 259 s Witness saw only `Filling`, `Mixing` (MixTank) and `Running` (Pasteurizer, Filler, Capper). Should there be one shared `EquipmentState` Enumeration Type or one per equipment type, and what is the full value list (e.g. idle, fault, CIP states)? Until that is known, State stays `TVQ{Value=xsd:string}`.
3. **MainPower.** It carries plant-wide demand and energy, so it may be a site-level meter, not Utilities equipment. It is modeled as a `PowerMeter` Unit under Utilities because that is where it sits in the browse tree. Confirm the type name and placement.
4. **Simulator nodes.** `DemoPlant.Simulator.Heartbeat` (Int64, about 1/s) and `DemoPlant.Simulator.Version` ("1.0.0") are server diagnostics and are left out. Should they be modeled as connection-health signals anyway?
5. **Counter and total reset behavior.** BatchCount, GoodCount, RejectCount, TotalLiters and EnergyKwh only rose (or stayed flat) while observed. Do they reset per shift, batch or day, or are they lifetime totals? This matters for any derived metrics later.

# Source Bindings

**Entity definitions** (every definition is a map; one-row maps for single instances)

| Definition id | Type | instanceId template | label template | map columns (name: data) | property -> binding template |
|---|---|---|---|---|---|
| areas | isa95-equipment:Area | `DemoPlant.[Area]` | `[Label]` | Area: Processing, Packaging, Utilities; Label: Processing, Packaging, Utilities | (no properties) |
| mix-tanks | MixTank | `DemoPlant.Processing.[Unit]` | `[Label]` | Unit: MixTank101; Label: Mix Tank 101 | State -> `con_d0a001/DemoPlant.Processing.[Unit].State`; LevelPct -> `con_d0a001/DemoPlant.Processing.[Unit].LevelPct`; TempSetpointC -> `con_d0a001/DemoPlant.Processing.[Unit].TempSetpointC`; TemperatureC -> `con_d0a001/DemoPlant.Processing.[Unit].TemperatureC`; AgitatorRpm -> `con_d0a001/DemoPlant.Processing.[Unit].AgitatorRpm`; AgitatorRunning -> `con_d0a001/DemoPlant.Processing.[Unit].AgitatorRunning`; BatchCount -> `con_d0a001/DemoPlant.Processing.[Unit].BatchCount` |
| pasteurizers | Pasteurizer | `DemoPlant.Processing.[Unit]` | `[Label]` | Unit: Pasteurizer201; Label: Pasteurizer 201 | State -> `con_d0a001/DemoPlant.Processing.[Unit].State`; HoldTempSetpointC -> `con_d0a001/DemoPlant.Processing.[Unit].HoldTempSetpointC`; HoldTempC -> `con_d0a001/DemoPlant.Processing.[Unit].HoldTempC`; FlowLpm -> `con_d0a001/DemoPlant.Processing.[Unit].FlowLpm`; TotalLiters -> `con_d0a001/DemoPlant.Processing.[Unit].TotalLiters` |
| fillers | Filler | `DemoPlant.Packaging.[WorkCell]` | `[Label]` | WorkCell: Filler301; Label: Filler 301 | State -> `con_d0a001/DemoPlant.Packaging.[WorkCell].State`; Running -> `con_d0a001/DemoPlant.Packaging.[WorkCell].Running`; SpeedBpm -> `con_d0a001/DemoPlant.Packaging.[WorkCell].SpeedBpm`; GoodCount -> `con_d0a001/DemoPlant.Packaging.[WorkCell].GoodCount`; RejectCount -> `con_d0a001/DemoPlant.Packaging.[WorkCell].RejectCount`; FillVolumeMl -> `con_d0a001/DemoPlant.Packaging.[WorkCell].FillVolumeMl` |
| cappers | Capper | `DemoPlant.Packaging.[WorkCell]` | `[Label]` | WorkCell: Capper302; Label: Capper 302 | State -> `con_d0a001/DemoPlant.Packaging.[WorkCell].State`; TorqueNm -> `con_d0a001/DemoPlant.Packaging.[WorkCell].TorqueNm` |
| conveyors | Conveyor | `DemoPlant.Packaging.[WorkCell]` | `[Label]` | WorkCell: Conveyor303; Label: Conveyor 303 | SpeedMps -> `con_d0a001/DemoPlant.Packaging.[WorkCell].SpeedMps`; MotorCurrentA -> `con_d0a001/DemoPlant.Packaging.[WorkCell].MotorCurrentA` |
| boilers | Boiler | `DemoPlant.Utilities.[Unit]` | `[Label]` | Unit: Boiler; Label: Boiler | SteamPressureBar -> `con_d0a001/DemoPlant.Utilities.[Unit].SteamPressureBar`; StackTempC -> `con_d0a001/DemoPlant.Utilities.[Unit].StackTempC` |
| air-compressors | AirCompressor | `DemoPlant.Utilities.[Unit]` | `[Label]` | Unit: AirCompressor; Label: Air Compressor | PressureBar -> `con_d0a001/DemoPlant.Utilities.[Unit].PressureBar`; Running -> `con_d0a001/DemoPlant.Utilities.[Unit].Running` |
| power-meters | PowerMeter | `DemoPlant.Utilities.[Unit]` | `[Label]` | Unit: MainPower; Label: Main Power | DemandKw -> `con_d0a001/DemoPlant.Utilities.[Unit].DemandKw`; EnergyKwh -> `con_d0a001/DemoPlant.Utilities.[Unit].EnergyKwh` |

**Relationship definitions**

| Definition id | relationship | source template | target template | map columns |
|---|---|---|---|---|
| site-areas | siteContains | `DemoPlant` | `DemoPlant.[Area]` | Area: Processing, Packaging, Utilities |
| processing-mix-tanks | areaContainsUnit | `DemoPlant.Processing` | `DemoPlant.Processing.[Unit]` | Unit: MixTank101 |
| processing-pasteurizers | areaContainsUnit | `DemoPlant.Processing` | `DemoPlant.Processing.[Unit]` | Unit: Pasteurizer201 |
| packaging-fillers | areaContainsWorkCell | `DemoPlant.Packaging` | `DemoPlant.Packaging.[WorkCell]` | WorkCell: Filler301 |
| packaging-cappers | areaContainsWorkCell | `DemoPlant.Packaging` | `DemoPlant.Packaging.[WorkCell]` | WorkCell: Capper302 |
| packaging-conveyors | areaContainsWorkCell | `DemoPlant.Packaging` | `DemoPlant.Packaging.[WorkCell]` | WorkCell: Conveyor303 |
| utilities-boilers | areaContainsUnit | `DemoPlant.Utilities` | `DemoPlant.Utilities.[Unit]` | Unit: Boiler |
| utilities-air-compressors | areaContainsUnit | `DemoPlant.Utilities` | `DemoPlant.Utilities.[Unit]` | Unit: AirCompressor |
| utilities-power-meters | areaContainsUnit | `DemoPlant.Utilities` | `DemoPlant.Utilities.[Unit]` | Unit: MainPower |

**Root instance** (plain definition, no map)
- instanceId `DemoPlant`, type `isa95-equipment:Site`, label `Demo Plant`, no properties.

# Prerequisites Outside Atlas
- **Done:** Connect OPC UA connector `con_d0a001` (alias `demo-plant-opcua`) is running against `opc.tcp://opcua-sim:4840` and advertises all 30 DemoPlant paths.
- **Timebase Connect OPC UA connector** pointed at `opc.tcp://opcua-sim:4840` (Flow OPC UA Simulator 1.0.0).
  - **Login:** user `timebase` with a user name and password token. Security policy is **None**, so the channel is unencrypted. Enter the password when you create the connector.
  - **Browse depth:** at least 4 levels under Objects (DemoPlant → Area → equipment → variable). All 30 variables are in namespace `ns=2` with string NodeIds that match the dot path (e.g. `ns=2;s=DemoPlant.Processing.MixTank101.LevelPct`).
  - **Publishing interval:** 1000 ms or faster. The fastest signals update about 59–60 times per minute; states, setpoints and BatchCount change rarely.
- After the connector exists, put its connector id in place of the literal `con_d0a001` in every binding template.
- The 28 bound variables must be subscribed and historized through Connect so the TVQ properties have data. The two `Simulator` nodes don't need to be.
- Nothing else is needed: the server has no other endpoints, namespaces or devices.

# Mapping Notes
- **Areas, not WorkCenters:** Processing, Packaging and Utilities have no variables and sit directly under the site. They are reused as `isa95-equipment:Area` with `siteContains`. The missing WorkCenter level is covered by `areaContainsUnit` and `areaContainsWorkCell`, both narrowing `equipmentContains`.
- **One type per object:** every object has its own variable set, so there are eight single-instance types, each mapped as a one-row map. MainPower is typed `PowerMeter` because its signals are demand and energy. This is a judgment call (Open Question 3).
- **Unit vs WorkCell:** MixTank, Pasteurizer, Boiler and AirCompressor are process or utility equipment, so they derive from Unit. Filler, Capper and Conveyor are discrete stations, so they derive from WorkCell.
- **Integer counters as doubles:** BatchCount (Int32), GoodCount and RejectCount (Int64) are pinned to xsd:double per the TVQ rule. That is exact up to 2^53, far above the observed values (about 53k).
- **Setpoints:** TempSetpointC and HoldTempSetpointC are the only writable nodes. They are bound read-only as TVQ properties and flagged as setpoints in their notes. Neither changed while observed.
- **State enumeration candidates:** observed values are `Filling`/`Mixing` (MixTank) and `Running` (the rest), from a 259 s window only. State is kept as an xsd:string TVQ until the full list is confirmed. Filler and AirCompressor also expose a Boolean `Running`, which overlaps with State on the Filler.
- **Left out on purpose:** `DemoPlant.Simulator` (Heartbeat, Version) is a server diagnostic, not equipment, so it has no type, instance or binding.
- **Units in notes only:** units come from EngineeringUnits and are kept in property notes. No static UOM properties were added, since each property's unit is fixed and already in its name.