#!/bin/bash
# Start/stop/query whatever is driving the LED panel.
#
#   fpp-panel-ctl.sh status                    # worldclock, the historic form
#   fpp-panel-ctl.sh scoreboard status         # a named service
#   fpp-panel-ctl.sh nfl start                 # ditto
#   fpp-panel-ctl.sh current restart           # whatever is live right now
#
# The one-argument form is kept because the HTTP control server and Home
# Assistant have been calling it that way since it was written, and it is not
# worth a coordinated change to rename an action that already works.
set -euo pipefail

FPP_BIN=/home/fpp/fpp-worldclock-venv/bin/fpp
FPP_API=http://127.0.0.1/api

# Long-running loops that own the panel and rebuild their own playlists.
DISPLAY_SERVICES="fpp-worldclock.service fpp-scoreboard.service fpp-nfl.service"

case "$#" in
  1) SVCKEY=worldclock; ACTION="$1" ;;
  2) SVCKEY="$1";       ACTION="$2" ;;
  *) echo "usage: $0 [worldclock|scoreboard|nfl|current] {start|stop|restart|enable|disable|status}" >&2; exit 1 ;;
esac

active_display_service() {
  for svc in $DISPLAY_SERVICES; do
    if systemctl is-active --quiet "$svc"; then
      echo "$svc"
      return 0
    fi
  done
  return 1
}

# Only ONE display service may own the panel. Both drive it on a loop, so
# leaving the other running means the two fight and the display flickers
# between them every few seconds.
stand_down_others() {
  for other in $DISPLAY_SERVICES; do
    [ "$other" = "$SVC" ] && continue
    sudo /usr/bin/systemctl stop "$other" 2>/dev/null || true
  done
}

current_playlist() {
  curl -s -m 5 "$FPP_API/fppd/status" | jq -r '.current_playlist.playlist // ""'
}

# The "nothing is a service" case: an ordinary animation playlist is up, and the
# useful repair is to make it start over rather than to touch any unit.
restart_playlist() {
  local name encoded
  name=$(current_playlist)
  if [ -z "$name" ]; then
    echo "idle"
    return 0
  fi
  encoded=$(printf '%s' "$name" | jq -sRr @uri)
  curl -s -m 5 -o /dev/null "$FPP_API/playlists/stop" || true
  sleep 2
  curl -s -m 5 -o /dev/null "$FPP_API/playlist/$encoded/start/1" || true
  echo "restarted playlist $name"
}

case "$SVCKEY" in
  worldclock) SVC=fpp-worldclock.service ;;
  scoreboard) SVC=fpp-scoreboard.service ;;
  # Same binary as scoreboard, different --league. A separate unit rather than
  # a flag on the old one because the two seasons overlap from September to
  # January, and switching sports should not mean editing an ExecStart line.
  nfl)        SVC=fpp-nfl.service ;;
  # Resolved at call time, so "fix whatever is live" needs no argument and no
  # guess from the caller. Home Assistant's own sensors are up to 15s stale;
  # the device knows the truth now.
  current)    SVC=$(active_display_service || true) ;;
  *) echo "unknown service: $SVCKEY" >&2; exit 1 ;;
esac

# current, with no display service running
if [ -z "${SVC:-}" ]; then
  case "$ACTION" in
    restart) restart_playlist; exit 0 ;;
    status)
      name=$(current_playlist)
      [ -n "$name" ] && echo "playlist:$name" || echo "idle"
      exit 0
      ;;
    stop)
      "$FPP_BIN" --host 127.0.0.1 stop
      exit 0
      ;;
    *) echo "no display service is running" >&2; exit 1 ;;
  esac
fi

case "$ACTION" in
  start)
    stand_down_others
    sudo /usr/bin/systemctl start "$SVC"
    ;;
  stop)
    sudo /usr/bin/systemctl stop "$SVC"
    "$FPP_BIN" --host 127.0.0.1 stop
    ;;
  restart)
    # restart stands the others down too. It did not, and when a second display
    # service arrived that became a live bug: restarting the world clock while
    # the scoreboard was running left BOTH units active and the panel flipping
    # between them every few seconds. "Restart X" plainly means X should be the
    # thing on the panel.
    stand_down_others
    sudo /usr/bin/systemctl restart "$SVC"
    ;;
  enable)    sudo /usr/bin/systemctl enable  "$SVC" ;;
  disable)   sudo /usr/bin/systemctl disable "$SVC" ;;
  status)
    # "current status" answering "active" is true and useless — the whole point
    # of asking is to find out WHICH thing is live. A named service still gets
    # the plain systemd answer, since that is what the sensors parse.
    if [ "$SVCKEY" = "current" ]; then
      echo "${SVC%.service}" | sed 's/^fpp-//'
    else
      sudo /usr/bin/systemctl is-active "$SVC"
    fi
    ;;
  *) echo "usage: $0 [worldclock|scoreboard|nfl|current] {start|stop|restart|enable|disable|status}" >&2; exit 1 ;;
esac
