"""Prometheus metrics exporter for Falcon Player FPP.

Scrape endpoint: http://<host>:9666/metrics
"""

from __future__ import annotations

import os
import time

import click
from prometheus_client import Gauge, Info, start_http_server

from .client import FPPClient

FPP_HOST = os.environ.get("FPP_HOST", "192.168.1.66")
DEFAULT_PORT = 9666
DEFAULT_INTERVAL = 15  # seconds between scrapes

# ------------------------------------------------------------------ metrics

fpp_up = Gauge("fpp_up", "1 if FPP device is reachable, 0 otherwise")
fpp_status = Gauge("fpp_status_mode", "FPP status mode code")
fpp_volume = Gauge("fpp_volume", "Current audio volume (0–100)")
fpp_uptime = Gauge("fpp_uptime_seconds", "FPP process uptime in seconds")

fpp_playing = Gauge("fpp_playing", "1 if something is currently playing")
fpp_playlist_name = Info("fpp_current_playlist", "Currently active playlist")
fpp_sequence_name = Info("fpp_current_sequence", "Currently active sequence")

fpp_cpu_usage = Gauge("fpp_cpu_usage_percent", "FPP host CPU usage %")
fpp_memory_usage = Gauge("fpp_memory_usage_percent", "FPP host memory usage %")
fpp_disk_free = Gauge("fpp_disk_free_bytes", "Free disk space in bytes")


def collect(host: str) -> None:
    try:
        with FPPClient(host) as fpp:
            s = fpp.status()
        fpp_up.set(1)
    except Exception:
        fpp_up.set(0)
        fpp_playing.set(0)
        return

    mode = s.get("status", 0)
    fpp_status.set(mode)
    fpp_playing.set(1 if mode != 0 else 0)
    fpp_volume.set(s.get("volume", 0))
    fpp_uptime.set(s.get("uptimeTotalSeconds", 0))

    current = s.get("current_playlist", {})
    fpp_playlist_name.info({"name": current.get("playlist", "")})
    fpp_sequence_name.info({"name": s.get("current_sequence", "")})

    sensors = s.get("sensors", {})
    fpp_cpu_usage.set(sensors.get("cpu", {}).get("load", 0))
    fpp_memory_usage.set(sensors.get("memory", {}).get("percentage", 0))
    fpp_disk_free.set(sensors.get("disk", {}).get("freeBytes", 0))


@click.command()
@click.option("--host", default=FPP_HOST, envvar="FPP_HOST", show_default=True)
@click.option("--port", default=DEFAULT_PORT, show_default=True,
              help="Port to expose /metrics on")
@click.option("--interval", default=DEFAULT_INTERVAL, show_default=True,
              help="Seconds between FPP polls")
def main(host: str, port: int, interval: int) -> None:
    """Run the FPP Prometheus exporter."""
    click.echo(f"Starting FPP exporter on :{port} (polling {host} every {interval}s)")
    start_http_server(port)
    while True:
        collect(host)
        time.sleep(interval)
