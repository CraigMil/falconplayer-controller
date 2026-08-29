# What's On — sports schedule display for the FPP panel

Date: 2026-08-29
Status: approved design, not yet implemented

## Purpose

A display service for the 192x192 LED panel that answers one question: *what
sport worth watching is on today and tomorrow, and what channel is it on?*

It is a **schedule board**, not a scoreboard. `fpp scoreboard` and `fpp nfl`
already show live scores for chosen leagues. This service surveys everything,
ranks it, and tells you where to watch — filtered so that nothing appears that
the user cannot actually watch in the USA.

Invoked on demand like the other display services. Not enabled at boot.

## Scope

In scope: a new `fpp whatson` command and `fpp-whatson.service`, the
`oddities.yaml` seed file, device registration, and Home Assistant wiring.

Out of scope: any weekly auto-refresh cron for the oddities file; any change to
`scoreboard`, `nfl`, or `worldclock` behaviour beyond registering the new
service alongside them.

## Data sources

All from the unauthenticated ESPN site API, one call per slug, over a
today+tomorrow date range:
`https://site.api.espn.com/apis/site/v2/sports/<slug>/scoreboard?dates=YYYYMMDD-YYYYMMDD`

| Tier | Slugs |
|---|---|
| Football | `football/nfl`, `football/college-football` |
| Soccer | `soccer/eng.1`, `soccer/uefa.champions`, `soccer/uefa.europa`, `soccer/eng.fa`, `soccer/conmebol.libertadores`, `soccer/conmebol.sudamericana`, `soccer/concacaf.champions` |
| Tennis | `tennis/atp`, `tennis/wta` — `major: true` tournaments only |
| Motorsport | `racing/f1` |
| Oddity | `data/oddities.yaml` (curated windows) |

All slugs verified live on 2026-08-29. Out-of-season slugs return `events: []`,
which is correct behaviour and not an error — `eng.fa` and
`concacaf.champions` both do so today.

IndyCar (`racing/irl`) and NASCAR (`racing/nascar-premier`) are deliberately
excluded: American-only race series are not of interest.

### Structural note: three event shapes

The API does not present a uniform "event". Three adapters are required.

1. **Match-shaped** (NFL, NCAAF, soccer) — one event is one game.
   `competitions[0]` holds the teams, status and broadcasts.
2. **Tournament-shaped** (tennis) — one event is a whole tournament, with
   `groupings[].competitions[]` holding individual matches. The US Open returns
   239 of them. Default slide is tournament-level, never per-match.
3. **Session-shaped** (F1) — one event is a race weekend;
   `competitions[]` are sessions, each with its own date and broadcast, keyed
   by `type.abbreviation` (`FP1`, `FP2`, `FP3`, `Qual`, `Sprint`, `Race`).

## Timezone

`America/Los_Angeles` (PDT) everywhere. Day boundaries for "today" and
"tomorrow" are PDT midnight; all times render as PDT. ESPN returns UTC.

This matters more than it looks: a 12:30pm ET NFL game is 9:30am PDT, and a UCL
midweek match is a 12:00pm PDT lunch game. A game that is "tomorrow" in PDT may
already be two days on in UTC — see testing.

## Channel filtering

Read `competitions[].geoBroadcasts[].media.shortName`. Normalise known variants
(`USA Net` -> `USA`, `NBC Sports` -> `NBC`). Then classify into three tiers:

**Watchable** — the user has it. Shows normally.
Broadcast and cable (NBC, CBS, ABC, FOX, ESPN, ESPN2, ESPNU, FS1, FS2, USA,
TNT, TBS, truTV, CNBC, Golf Channel, BTN, SEC Network, ACCN), plus Peacock,
Paramount+, CBS Sports Network, ESPN+, Apple TV, Prime Video, Netflix, Max,
and Fox apps.

**Payable** — a service the user could buy but does not have.
DAZN, Fubo-exclusive, beIN, FloSports, Victory+, Willow, WRC+.
**Shown only if the event is major**, and marked on the slide.

**Unavailable** — no US broadcast listed at all, or a foreign-language-only
feed. Dropped unconditionally. `Universo` or `TUDN` alone is unavailable;
paired with an English channel the event is watchable.

### Definition of "major"

The payable tier leaks without a hard definition. An event is major if any of:

- it is a **final, semifinal, or quarterfinal** of a tracked competition;
- it is a **tennis tournament with `major: true`** (the Slams);
- it is an **F1 Race** session (not Sprint, Qual or practice);
- it carries `major: true` (or falls after `major_from:`) in `oddities.yaml`.

A group-stage Sudamericana tie or a Tuesday darts preliminary is not major, and
so is dropped when it is on a service the user does not have.

## Caps and ranking

Per-sport caps, guaranteeing variety over completeness. A single NCAAF Saturday
is ~50 games; today+tomorrow across all tiers can exceed 80 events.

| Sport | Cap |
|---|---|
| NFL | 3 |
| NCAAF | 3 |
| EPL | 3 |
| Cups (all soccer cup slugs combined) | 2 |
| Tennis | 2 |
| F1 | 2 |
| Oddity | 1 |

Maximum 16 event cards plus 2 day dividers.

Ranking within each bucket, in order:

1. **Day** — today before tomorrow.
2. **Live tier** — live, then starting within 2h, then later today, then tomorrow.
3. **Drama score**, applied within the live tier: a one-score margin in the 4th
   quarter, a tied soccer match past 75', a tennis match in a deciding set. A
   blowout in the 3rd ranks below a tight game that just kicked off.
4. **Round weight** — final > semi > quarter > group. For F1, Race > Sprint > Qual.
5. **AP ranking** for NCAAF.
6. **National network** over streaming-only.
7. **Watchable over payable** — payable events fill leftover slots rather than
   displacing games the user can simply turn on.
8. Ties break on kickoff time.

F1 practice sessions (`FP1`/`FP2`/`FP3`) are excluded unless
`include_practice: true` is set in config; otherwise a GP weekend consumes both
motorsport slots with Friday practice.

Tennis promotion rule: the tournament-level card is the default, but when a
major has a live match in a **deciding set** (5th for men, 3rd for women), that
match is promoted to its own match-level card and consumes one tennis slot. Two
such matches at once produce two cards and the tournament card drops. This is
the only circumstance in which a per-match tennis card exists.

## Slides

192x192, built on the existing `Frame` in `src/fpp/canvas.py`. `text_fit`
handles shrink-to-fit; `paste` handles logos, reusing the fetch-and-cache
already in `soccer.py`.

Order: `[TODAY divider][today's events, ranked][TOMORROW divider][tomorrow's events, ranked]`.

### Day divider

    TODAY            size 34
    SAT · AUG 29     size 16 dimmed
    6 events         size 13

### Event card (match-shaped)

    NCAAF       9:30a      26px league-coloured strip
    -----------------
    (logo)   (logo)
    SJSU  @  #21 USC       text_fit from size 22
    0-0        0-0         records, size 11 dimmed
    -----------------
    NBC                    36px channel strip, size 20

When live, the strip's right slot shows `● LIVE Q3` in red, and the records
line is replaced by the score.

### Single-title card (tennis, F1, oddity)

    TENNIS     ALL DAY
    -----------------
    US OPEN            size 26
    Round of 16        size 14
    Men's & Women's    size 12 dimmed
    -----------------
    ESPN · ESPN+

F1 uses the same layout: event name, session (`RACE`), circuit, channel. A live
F1 session shows lap count in place of the score line. A promoted live tennis
match shows the set scores and a `● LIVE 5th` indicator.

### Payable marking

The bottom channel strip is recoloured amber and the service prefixed with `$`,
e.g. `$ DAZN`. No extra card space is consumed.

### Empty state

A Tuesday in June may yield nothing. Rather than a blank panel, render one card:
`NOTHING ON`, with `next: EPL Sat 4:30a` computed from the first fixture beyond
the window.

## Refresh and dwell

Dwell reuses the scoreboard's shrink-to-fit rule:
`min(--interval, --cycle / n)` floored at `--min-interval`, defaulting
12s / 180s / 6s, keeping a lap under three minutes.

Refresh is adaptive: **every 60s while anything is live**, every 10 minutes
when nothing is. Live data goes stale fast; idle data does not. The calls are
small and unauthenticated.

A fetch failure is non-fatal — the loop renders the empty-state card and
retries rather than exiting to `Restart=on-failure`.

## oddities.yaml

Hand-curated windows, checked in. Format:

    - name: PDC World Darts Championship
      subtitle: "Ally Pally"
      start: 2026-12-13
      end:   2027-01-03
      channel: ESPN+
      major_from: 2026-12-30    # final week ranks as major
    - name: Tour de France
      start: 2027-07-03
      end:   2027-07-25
      channel: Peacock
      major: true

Seed set: PDC World Darts, World Snooker Championship, Tour de France,
Iditarod, the six sumo basho, World Chess Championship, cyclocross worlds,
curling worlds, Le Mans, Isle of Man TT, and WRC rally rounds.

WRC's US home is WRC+, a paid service, so rally sits in the payable tier: major
rounds (Monte Carlo, Safari, Finland) appear marked `$ WRC+`, lesser rounds do
not appear at all. This is the filter working as designed, but it does mean
rally appears rarely.

Dates beyond a year out are approximate by nature. The file carries a comment
saying so. Stale entries fail safe by simply not matching today or tomorrow.

## Device integration

Five files in `device/`:

1. **`fpp-whatson.service`** (new), modelled on `fpp-scoreboard.service`:
   `ExecStart=/home/fpp/fpp-worldclock-venv/bin/fpp --host 127.0.0.1 whatson --interval 12 --cycle 180`,
   `Restart=on-failure`, `After=network-online.target fpp.service`.
   **Not enabled at boot** — the user never reboots the FPP, and leaving all
   three display services disabled at boot keeps the existing README claim true.
2. **`fpp-panel-ctl.sh`** — add `fpp-whatson.service` to `DISPLAY_SERVICES`, a
   `whatson)` branch in the `SVCKEY` case, and `whatson` to both usage strings.
   The `DISPLAY_SERVICES` entry is what makes `stand_down_others()` stop it when
   another display starts. Without it the services fight and the panel flickers
   every few seconds.
3. **`panel-control-server.py`** — add `"whatson"` to `_SERVICES`. Routing is
   generic; nothing else changes.
4. **`sudoers-fpp-whatson`** — the same six-verb NOPASSWD line as
   `sudoers-fpp-nfl`, for `fpp-whatson.service`.
5. **`README.md`** — document the new service alongside the others.

## Home Assistant integration

A display service that exists only on the Falcon Player is unreachable in
practice, and worse, HA's scripts enumerate display services by name in order to
stop them. Five places in `~/Coding/HomeAssistant`:

1. `config/configuration.yaml` — `rest_command.whatson_start` / `_stop`, a
   `rest:` sensor on `http://192.168.1.66:8090/whatson/status`, and a branch in
   the `FPP Panel Show` template sensor.
2. `config/scripts.yaml` — a `fpp_whatson_start` script; add the whatson stop
   call to **both** `fpp_play_animation` and `fpp_panel_stop`; add the sensor to
   `fpp_refresh_status`.
3. `config/dashboards/worldclock.yaml` — a button and a status row.
4. Deploy the config, then push the dashboard separately — it is storage-mode.
5. Validate, then reload without restarting.

## Testing

Pure-function unit tests, no network, using fixtures captured from live ESPN
responses (a real NCAAF Saturday, a US Open day, an F1 weekend, an empty FA Cup
response):

- channel classification into watchable / payable / unavailable, including the
  English+Spanish pairing case and the empty-broadcast case;
- the `major` definition across all four of its clauses;
- per-sport caps;
- live-tier and drama ordering;
- the tennis deciding-set promotion, including the two-at-once case;
- F1 session selection and practice exclusion;
- **the PDT day-boundary split**, including an event that is "tomorrow" in PDT
  but already the day after in UTC. This is the bug this design is most likely
  to have.

Render smoke tests: every card type renders to a JPEG without exception,
including a live tennis card, a payable card, and the empty state.

Manual check: `fpp whatson --dry-run --out /tmp/cards` writes PNGs locally so a
real day can be eyeballed before anything touches the panel.

## New files

    src/fpp/displays/whatson.py
    src/fpp/data/oddities.yaml
    device/fpp-whatson.service
    device/sudoers-fpp-whatson
    tests/test_whatson.py
