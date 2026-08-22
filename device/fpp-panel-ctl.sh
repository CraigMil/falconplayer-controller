#!/bin/bash
# Start/stop/query one of the panel's long-running display services.
#
#   fpp-panel-ctl.sh status                    # worldclock, the historic form
#   fpp-panel-ctl.sh scoreboard status         # any registered service
#
# The one-argument form is kept because the HTTP control server and Home
# Assistant have been calling it that way since it was written, and it is not
# worth a coordinated change to rename an action that already works.
set -euo pipefail

FPP_BIN=/home/fpp/fpp-worldclock-venv/bin/fpp

case "$#" in
  1) SVCKEY=worldclock; ACTION="$1" ;;
  2) SVCKEY="$1";       ACTION="$2" ;;
  *) echo "usage: $0 [service] {start|stop|restart|enable|disable|status}" >&2; exit 1 ;;
esac

case "$SVCKEY" in
  worldclock) SVC=fpp-worldclock.service ;;
  scoreboard) SVC=fpp-scoreboard.service ;;
  *) echo "unknown service: $SVCKEY" >&2; exit 1 ;;
esac

# Only ONE display service may own the panel. Both drive it on a loop and
# rebuild their own playlists, so leaving the other running means the two fight
# and the display flickers between them every few seconds.
stand_down_others() {
  for other in fpp-worldclock.service fpp-scoreboard.service; do
    [ "$other" = "$SVC" ] && continue
    sudo /usr/bin/systemctl stop "$other" 2>/dev/null || true
  done
}

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
    # restart has to stand the others down too. It did not, and when a second
    # display service arrived that became a live bug: restarting the world
    # clock while the scoreboard was running left BOTH units active and the
    # panel flipping between fpp-worldclock-a and fpp-scoreboard every few
    # seconds. "Restart X" plainly means X should be the thing on the panel.
    stand_down_others
    sudo /usr/bin/systemctl restart "$SVC"
    ;;
  enable)    sudo /usr/bin/systemctl enable  "$SVC" ;;
  disable)   sudo /usr/bin/systemctl disable "$SVC" ;;
  status)    sudo /usr/bin/systemctl is-active "$SVC" ;;
  *) echo "usage: $0 [service] {start|stop|restart|enable|disable|status}" >&2; exit 1 ;;
esac
