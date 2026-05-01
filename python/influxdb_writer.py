"""
influxdb_writer.py — InfluxDB 2.x Time-Series Writer
=====================================================

Writes sensor data and peak alert events to InfluxDB for historical
persistence. Used by the main bridge (mqtt_publisher.py) to store
every reading and every detection event.

Measurements:
  - power_data:   continuous sensor readings (power, current, voltage, status)
  - peak_alerts:  discrete peak detection events with reason

Gracefully degrades: if InfluxDB is unreachable, logs a warning and
continues without crashing.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (from environment)
# ---------------------------------------------------------------------------
INFLUXDB_URL    = os.environ.get("INFLUXDB_URL",    "http://localhost:8086")
INFLUXDB_TOKEN  = os.environ.get("INFLUXDB_TOKEN",  "peak-token-group25")
INFLUXDB_ORG    = os.environ.get("INFLUXDB_ORG",    "group25")
INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "peak_load")


class InfluxDBWriter:
    """
    Non-blocking, fault-tolerant InfluxDB writer with batching.

    Usage:
        writer = InfluxDBWriter()
        if writer.connect():
            writer.write_sensor_data(power_w=1.5, current_a=0.3, ...)
            writer.write_peak_alert(power_w=2.1, reason="THRESHOLD")
        writer.close()
    """

    def __init__(
        self,
        url: str = INFLUXDB_URL,
        token: str = INFLUXDB_TOKEN,
        org: str = INFLUXDB_ORG,
        bucket: str = INFLUXDB_BUCKET,
    ) -> None:
        self._url = url
        self._token = token
        self._org = org
        self._bucket = bucket
        self._client = None
        self._write_api = None
        self._connected = False

    def connect(self) -> bool:
        """
        Initialize the InfluxDB client with batching.
        Returns True if connection succeeds, False otherwise.
        """
        try:
            from influxdb_client import InfluxDBClient
            from influxdb_client.client.write_api import SYNCHRONOUS

            self._client = InfluxDBClient(
                url=self._url,
                token=self._token,
                org=self._org,
                timeout=5000,
            )

            # Quick health check
            health = self._client.health()
            if health.status != "pass":
                logger.warning(
                    "[InfluxDB] Health check failed: %s", health.message
                )
                return False

            self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
            self._connected = True
            logger.info(
                "[InfluxDB] Connected to %s (org=%s, bucket=%s)",
                self._url, self._org, self._bucket,
            )
            return True

        except ImportError:
            logger.warning(
                "[InfluxDB] influxdb-client not installed. "
                "Install with: pip install influxdb-client"
            )
            return False
        except Exception as exc:
            logger.warning(
                "[InfluxDB] Connection failed: %s — continuing without InfluxDB", exc
            )
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def write_sensor_data(
        self,
        power_w: float,
        current_a: float,
        voltage_v: float,
        status: str,
        relay_on: bool,
        button_held: bool = False,
        ramp_w: float = 0.0,
    ) -> bool:
        """
        Write a sensor reading to the 'power_data' measurement.

        Returns True if write succeeded, False otherwise.
        """
        if not self._connected:
            return False

        try:
            from influxdb_client import Point

            point = (
                Point("power_data")
                .tag("status", status)
                .tag("relay", "ON" if relay_on else "OFF")
                .field("power_w", round(power_w, 3))
                .field("current_a", round(current_a, 4))
                .field("voltage_v", round(voltage_v, 2))
                .field("ramp_w", round(ramp_w, 3))
                .field("button_held", button_held)
                .time(datetime.now(timezone.utc))
            )

            self._write_api.write(bucket=self._bucket, record=point)
            return True

        except Exception as exc:
            logger.warning("[InfluxDB] Write sensor data failed: %s", exc)
            return False

    def write_peak_alert(
        self,
        power_w: float,
        reason: str,
        status: str = "PEAK_DETECTED",
    ) -> bool:
        """
        Write a peak detection event to the 'peak_alerts' measurement.

        Returns True if write succeeded, False otherwise.
        """
        if not self._connected:
            return False

        try:
            from influxdb_client import Point

            point = (
                Point("peak_alerts")
                .tag("reason", reason)
                .tag("status", status)
                .field("power_w", round(power_w, 3))
                .field("alert", 1)
                .time(datetime.now(timezone.utc))
            )

            self._write_api.write(bucket=self._bucket, record=point)
            logger.info("[InfluxDB] Peak alert written: %.3f W (%s)", power_w, reason)
            return True

        except Exception as exc:
            logger.warning("[InfluxDB] Write alert failed: %s", exc)
            return False

    def close(self) -> None:
        """Flush pending writes and close the client."""
        if self._write_api:
            try:
                self._write_api.close()
            except Exception:
                pass
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self._connected = False
        logger.info("[InfluxDB] Connection closed.")
