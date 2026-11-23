# Using Witness

## Connections (the home page)

**Connections** is the first item in the left menu and the page Witness opens on. Every MQTT broker and OPC UA server is listed in one list, styled like Datasets in Historian. Each row shows:

- the status dot, name and type;
- the address;
- a secure badge when TLS or OPC UA message security is on;
- the message or value-change rate.

| Do this | To |
| --- | --- |
| Select a row | Open that connection in its own tab |
| Select the arrow at the end of a row | Show its settings summary and 5-minute live status without leaving the list |
| Select the pencil | Edit it in the side panel (see [Connections and security](connections-and-security.md)) |
| Choose **Add connection** | Create a broker or server connection in the same panel. The **Type** dropdown switches between MQTT and OPC UA |

## Connection tabs

A connection tab shows only that connection. The header shows the name, type, security and address. The toolbar has:

- **Filter:** matches topic or node paths. `/` focuses it and `Esc` clears it.
- **Show $SYS** (MQTT only): includes the broker's own statistics topics.
- **Expand all** and **Collapse all:** apply to this connection's tree only.
- **Live messages:** opens a window under the browser with the latest 300 messages (MQTT) or value changes (OPC UA) for this connection. It follows the tree filter. Select a message to jump to its topic or node.

### Namespace browser

The left panel is the namespace browser. It is labelled **Namespace** for MQTT and **Address space** for OPC UA. Select a topic or node to see its value, type, quality, timestamp and a short trend in the detail panel on the right.

The button in the top-right corner of the browser panel expands the tree to the full width of the tab and hides the detail panel. Select it again, or press `Esc`, to restore the split. Each tab remembers its own selection, filter and expanded state when you switch tabs.

## Links

| Link | Opens |
| --- | --- |
| `#/conn` | Connections |
| `#/c/<connection id>` | A connection tab |
| `#/c/<connection id>/<path>` | A connection tab with a topic or node selected |
| `#/atlas` | Move to Timebase |

Older `#/ns/<broker>/…` and `#/ua/<server>/…` links still work. They open the matching connection tab.

## Keyboard

| Key | Action |
| --- | --- |
| `/` | Focus the filter |
| `Esc` | Clear the filter, or restore an expanded namespace browser |
| `Space` | Pause or resume live updates |

The theme button in the tab strip switches between light and dark. Your choice is saved in the browser.
