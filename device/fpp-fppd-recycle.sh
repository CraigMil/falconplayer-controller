#!/bin/bash
# Recycle fppd, putting the panel back exactly as it was found.
#
# WHY THIS EXISTS
# ---------------
# /opt/fpp/src/fppd is a 32-bit ARM binary, so it has ~3 GB of address space.
# PlaylistEntryImage::Init spawns a std::thread PER IMAGE ENTRY at playlist
# LOAD time, and each one wants an 8 MB contiguous stack. fppd's VmSize grows
# with uptime — measured at 2.25 GB after 27 days, with a 753 MB heap — until
# pthread_create returns EAGAIN and Playlist::Load throws. The whole playlist
# is then discarded with one line in fppd.log:
#
#   Playlist.cpp:447: Playlist fpp-scoreboard is invalid: Resource temporarily unavailable
#
# Nothing else reports it. The display service logs a clean cycle, the API says
# "playing", and the panel is BLACK. On 2026-09-23 the NFL board (22 image
# entries) could not load at all while 12 entries still could.
#
# A restart drops VmSize from 2.25 GB to 0.49 GB and the limit goes back above
# 40 image entries. This is a workaround, not a fix — the real fix is a 64-bit
# FPP image, since this Pi 4 is a Cortex-A72 running an armhf userland.
#
# ORDER MATTERS. Playback is stopped BEFORE fppd is touched: restarting while
# the decoder holds an mp4 open is the documented 2026-08-16 wedge (124,891
# "Invalid NAL unit size" errors, fppd.log at 21.2 MB, API unresponsive).

set -euo pipefail

PANEL_CTL=/home/fpp/fpp-panel-ctl.sh
FPP_API=http://127.0.0.1/api

log() { echo "fppd-recycle: $*"; }

# What owns the panel right now? Asked of the device rather than tracked here,
# and asked through fpp-panel-ctl.sh rather than by re-listing the units, so a
# sixth display service is picked up without editing this file.
#
# "current status" answers one of:
#   <key>           a display service is live (worldclock|scoreboard|nfl|...)
#   playlist:<name> an ordinary animation playlist is up, no service
#   idle            nothing is playing
state=$("$PANEL_CTL" current status 2>/dev/null || echo idle)
log "found: $state"

case "$state" in
  playlist:*) playlist="${state#playlist:}"; service="" ;;
  idle)       playlist=""; service="" ;;
  *)          playlist=""; service="$state" ;;
esac

# Stop the service first so it cannot push a fresh playlist into an fppd that
# is on its way down — these loops rebuild and restart every refresh interval.
if [ -n "$service" ]; then
  log "stopping display service: $service"
  "$PANEL_CTL" "$service" stop || true
fi

# Belt and braces: whatever the service did or did not do, make sure no media
# file is open before fppd goes down.
log "stopping playback"
curl -s -m 5 -o /dev/null "$FPP_API/playlists/stop" || true
sleep 3

before=$(awk '/VmSize/{print $2}' "/proc/$(pgrep -x fppd | head -1)/status" 2>/dev/null || echo "?")
log "VmSize before: ${before} kB"

log "restarting fppd"
systemctl restart fppd

# Condition, not a fixed sleep: fppd takes ~15s on this box but that is a
# measurement, not a contract, and a slow boot must not silently skip the
# restore below.
#
# The check is deliberately NOT a bare `curl -o /dev/null`. Apache serves the
# API and answers 503 on its own while fppd is down, and curl without --fail
# EXITS 0 on a 503 — so the naive loop breaks out on the first try and the
# restore races a daemon that is not up yet. Require --fail AND the daemon
# saying so itself.
fppd_ready() {
  curl -fsS -m 5 "$FPP_API/fppd/status" 2>/dev/null \
    | jq -e -r '.fppd == "running"' >/dev/null 2>&1
}

for _ in $(seq 1 40); do
  fppd_ready && break
  sleep 3
done

if ! fppd_ready; then
  log "ERROR: fppd did not come back within 120s — panel left stopped"
  exit 1
fi

after=$(awk '/VmSize/{print $2}' "/proc/$(pgrep -x fppd | head -1)/status" 2>/dev/null || echo "?")
log "VmSize after: ${after} kB"

# Put back what was there.
if [ -n "$service" ]; then
  log "restoring display service: $service"
  "$PANEL_CTL" "$service" start
elif [ -n "$playlist" ]; then
  log "restoring playlist: $playlist"
  encoded=$(printf '%s' "$playlist" | jq -sRr @uri)
  curl -s -m 5 -o /dev/null "$FPP_API/playlist/$encoded/start/1" || true
else
  log "was idle — leaving the panel idle"
fi

log "done"
