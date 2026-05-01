import os
import sys
import time
import socket

from contextlib import closing

MQTT_HOST = os.environ.get("MQTT_HOST", "mqtt-broker")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))


def tcp_check(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with closing(socket.create_connection((host, port), timeout=timeout)):
            return True
    except Exception:
        return False


def main():
    # simple TCP connect to broker
    ok = tcp_check(MQTT_HOST, MQTT_PORT, timeout=5.0)
    if ok:
        print(f"[healthcheck] MQTT {MQTT_HOST}:{MQTT_PORT} reachable")
        sys.exit(0)
    else:
        print(f"[healthcheck] MQTT {MQTT_HOST}:{MQTT_PORT} unreachable", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
