"""Adapters that turn a gateway connection into a SourceModel (see gateway/source_model.py)."""
from . import mqtt, opcua


def build(conn):
    """SourceModel for an OPC UA server or an MQTT broker (plain MQTT and Sparkplug B together)."""
    return opcua.build(conn) if conn.kind == "opcua" else mqtt.build(conn)
