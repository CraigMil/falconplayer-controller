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
| `fpp-worldclock-control.service` | `/etc/systemd/system/` |

The Python package itself is an **editable install** at
`/home/fpp/falconplayer-controller`, into the venv at
`/home/fpp/fpp-worldclock-venv`. To push a code change:

```bash
tar -czf - src/fpp | ssh fpp@192.168.1.66 \
  "cd /home/fpp/falconplayer-controller && tar -xzf -"
ssh fpp@192.168.1.66 "/home/fpp/fpp-panel-ctl.sh scoreboard restart"
```

## The two display services

`fpp-worldclock.service` and `fpp-scoreboard.service` are long-running loops that
each drive the panel and **rebuild their own playlist every cycle**. Only one may
run at a time — leaving both up makes them fight, and the display flickers
between them every few seconds. `fpp-panel-ctl.sh start` stops the other one
first, so nothing else has to remember.

For the same reason, playing an ordinary animation playlist means stopping both
services first, or one of them takes the panel back part-way through. Home
Assistant's `script.fpp_play_animation` does this.

Neither is enabled at boot, so a reboot leaves the panel idle.

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

Services: `worldclock`, `scoreboard`. Actions: `start`, `stop`, `restart`,
`status`. `sudo` is limited to exactly these units in `/etc/sudoers.d/`.

The bare one-segment paths are kept because Home Assistant has called them that
way since the server was written, and renaming them would have meant a
coordinated change across two repos to gain nothing.
