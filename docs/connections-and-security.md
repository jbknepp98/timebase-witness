# Connections and security

Connections are created and edited in **Connections > Add connection**, or with the pencil on a row. **Test connection** tries the settings without saving them. Saving reconnects only that connection. Unchecking **Connected** pauses a connection without deleting it, and **Delete** is in the edit dialog.

## MQTT

| Setting | Notes |
| --- | --- |
| Host, port | For example `mosquitto`, `1883` (or `8883` for TLS) |
| Transport | TCP or WebSockets, with a path for WebSockets |
| Protocol | MQTT 3.1.1 or 5 |
| Client ID | Leave empty for a generated one |
| User name, password | Optional |
| TLS | Optional CA certificate (PEM), optional client certificate and private key (PEM), and certificate verification on or off |
| Topic filters | One per line, for example `Enterprise/SiteA/#` and `spBv1.0/+/DDATA/#`. Defaults to `#` |
| `$SYS` statistics | Subscribes to the broker's statistics topics |

## OPC UA

| Setting | Notes |
| --- | --- |
| Endpoint | `opc.tcp://host:port[/path]`. **Discover** lists the server's endpoints, security policies and login types |
| Security policy | None, Basic256Sha256, Aes128Sha256RsaOaep or Aes256Sha256RsaPss |
| Security mode | Sign, or Sign and encrypt |
| Server certificate | Optionally pin the server's SHA-1 thumbprint. Without a pin, the server's certificate is accepted |
| Login | Anonymous, or user name and password |
| Branches to include | Browse paths to limit the connection to, one per line, for example `DemoPlant/Processing`. Empty means the whole Objects folder |
| Publishing interval | Milliseconds between value batches (default 500) |
| Connect connector | The Timebase Connect connector id used for Atlas bindings in Move to Timebase |

**Client certificate:** the gateway creates its own OPC UA application certificate the first time it starts. The certificate is valid for one year and its application URI is `urn:flow-software:lookout-gateway`. Download it from the connection dialog, or from `/api/opcua/client-cert.der`, and add it to a server's trusted clients when the server needs signed or encrypted channels.

## How secrets are stored

- Connections live in `lookout-data/connections.json`, which only the owner can read.
- Passwords and MQTT client private keys are encrypted with **Fernet** (AES-128-CBC with HMAC-SHA256). The key is `lookout-secret/master.key`, mounted read-only into the gateway and kept apart from the store.
- The API and the page only ever see whether a secret is set, never its value. When you edit a connection, leaving a password field empty keeps the stored one.
- Without a usable key file, the gateway logs a warning, the dialog warns that secrets will be stored as plain text before you save, and stored values are marked `plain`.
- Anyone with administrator access to the host can read both the store and the key. Encryption protects copies and backups of the store, not the host itself.
- **Back up `master.key` with `connections.json`.** Without the key, stored passwords cannot be decrypted and must be entered again.

## Access

Witness has no login yet. Anyone who can reach the page can add, edit and delete connections, but never read their secrets. Run it on a trusted network, or put an authenticating proxy in front of Caddy.
