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

fpp_cpu_temp = Gauge("fpp_cpu_temp_celsius", "FPP CPU temperature in Celsius")

# fppd's virtual address space. Not vanity: fppd is a 32-bit ARM binary, so it
# has ~3 GB total, and PlaylistEntryImage::Init spawns a thread wanting an 8 MB
# CONTIGUOUS stack for every image entry at playlist LOAD time. When VmSize gets
# close enough that no 8 MB hole is left, pthread_create returns EAGAIN,
# Playlist::Load throws, the whole playlist is discarded and THE PANEL GOES
# BLACK — with nothing reporting it but one line in fppd.log.
#
# Measured 2026-09-23: at 2.25 GB a 14-image playlist would not load; after a
# restart (0.49 GB) 40 loaded fine. So this is the metric that predicts the
# failure, and it is why fpp-fppd-recycle.timer exists.
#
# VmSize, not VmRSS, on purpose. What runs out is ADDRESS SPACE, not memory —
# RSS was only 1.8 GB on a 3.6 GB box when loads were already failing, so RSS
# looked healthy while the thing that mattered was nearly exhausted.
fpp_fppd_vmsize = Gauge("fpp_fppd_vmsize_bytes",
                        "fppd virtual address space in bytes (32-bit ceiling ~3 GiB)")


def _read_fppd_vmsize() -> float:
    """fppd's VmSize in bytes, or NaN if it cannot be read.

    Only meaningful when the exporter runs ON the device, which it does
    (fpp-exporter.service passes --host 127.0.0.1). Reading /proc needs no root:
    VmSize lives in /proc/<pid>/status, which is world-readable, unlike
    /proc/<pid>/maps.

    NaN rather than 0 when fppd is down: a 0 here would read as "all the address
    space in the world" and is exactly backwards. Grafana draws NaN as a gap.
    """
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/comm") as fh:
                    if fh.read().strip() != "fppd":
                        continue
                with open(f"/proc/{entry}/status") as fh:
                    for line in fh:
                        if line.startswith("VmSize:"):
                            # "VmSize:\t 2363728 kB"
                            return float(line.split()[1]) * 1024
            except (OSError, ValueError):
                # The process can exit between listdir and open. Keep looking.
                continue
    except OSError:
        pass
    return float("nan")


def collect(host: str) -> None:
    # Before the API call and outside its early return: if fppd is wedged the
    # HTTP API is the first thing to stop answering, and that is precisely when
    # its address-space usage is worth having.
    fpp_fppd_vmsize.set(_read_fppd_vmsize())

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

    for sensor in s.get("sensors", []):
        if sensor.get("valueType") == "Temperature" and "CPU" in sensor.get("label", ""):
            fpp_cpu_temp.set(sensor.get("value", 0))


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
