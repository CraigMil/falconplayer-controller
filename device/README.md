# What runs on the FPP box

These files live on the device (192.168.1.66) and are copied here so they are
reviewable and recoverable. They are **not** deployed from here automatically —
see the paths below.

| File | Installed at |
|---|---|
| `fpp-panel-ctl.sh` | `/home/fpp/fpp-panel-ctl.sh` |
| `panel-control-server.py` | `/home/fpp/panel-control-server.py` |
| `fpp-worldclock.service` | `/etc/systemd/system/` |
| `fpp-scoreboard.service` | `/etc/systemd/system/` |
| `fpp-nfl.service` | `/etc/systemd/system/` |
| `sudoers-fpp-nfl` | `/etc/sudoers.d/fpp-nfl` (mode 0440, root:root) |
| `fpp-whatson.service` | `/etc/systemd/system/` |
| `sudoers-fpp-whatson` | `/etc/sudoers.d/fpp-whatson` (mode 0440, root:root) |
| `fpp-worldclock-control.service` | `/etc/systemd/system/` |

The Python package itself is an **editable install** at
`/home/fpp/falconplayer-controller`, into the venv at
`/home/fpp/fpp-worldclock-venv`. To push a code change:

```bash
tar -czf - src/fpp | ssh fpp@192.168.1.66 \
  "cd /home/fpp/falconplayer-controller && tar -xzf -"
ssh fpp@192.168.1.66 "/home/fpp/fpp-panel-ctl.sh scoreboard restart"
```

## The four display services

`fpp-worldclock.service`, `fpp-scoreboard.service` (soccer), `fpp-nfl.service`
and `fpp-whatson.service` (what is on today and tomorrow, and on what channel)
are long-running loops that each drive the panel and **rebuild their own playlist
every cycle**. Only one may run at a time — leaving both up makes them fight, and the display flickers
between them every few seconds. `fpp-panel-ctl.sh start` stops the other one
first, so nothing else has to remember.

For the same reason, playing an ordinary animation playlist means stopping both
services first, or one of them takes the panel back part-way through. Home
Assistant's `script.fpp_play_animation` does this.

None of them is enabled at boot, so a reboot leaves the panel idle.

`fpp-whatson.service` needs two dependencies the others do not: `PyYAML` for its
editable config files and `segno` for the highlight QR codes. A `pip install -e`
into the venv brings both.

## The control API

`panel-control-server.py` on **:8090**, bearer token from
`/home/fpp/.worldclock-control-token`, so Home Assistant can start and stop units
that need root:

```
POST /start                  # world clock — the original, still supported
POST /scoreboard/start       # <service>/<action>
GET  /status
GET  /scoreboard/status
```

Services: `worldclock`, `scoreboard`, `nfl`, `whatson`, `current`. Actions: `start`, `stop`,
`restart`, `status`. There is a per-unit rule in `/etc/sudoers.d/` for each, but
it is **documentation of intent, not a constraint** — `010_pi-nopasswd` grants
`fpp` blanket `NOPASSWD: ALL`, so the narrow rules restrict nothing. Adding a
service still means adding its rule, so that the day the blanket grant goes away
nothing breaks.

The scoreboard and NFL units are the same binary with a different `--league`,
and they share the `fpp-scoreboard` playlist name and image files. That is safe
only because one display service runs at a time; each rebuilds the playlist from
scratch on start, so leftover images from the other are simply unreferenced.

**`current` is not a unit.** It resolves at call time to whichever display
service is live, or — when neither is — to the animation playlist FPP is
playing. `POST /current/restart` is therefore "unstick whatever is on the panel
without changing what is on it", which is the one repair `start` cannot make:
`systemctl start` on an already-active unit is a no-op, so a service that is up
but wedged can only be recovered by restarting it. `GET /current/status` answers
`worldclock`, `scoreboard`, `playlist:<name>` or `idle`.

Resolving on the device matters. Home Assistant's sensors are up to 15s stale,
so deciding there which service to restart can cheerfully restart the one that
was running a quarter of a minute ago.

The bare one-segment paths are kept because Home Assistant has called them that
way since the server was written, and renaming them would have meant a
coordinated change across two repos to gain nothing.
