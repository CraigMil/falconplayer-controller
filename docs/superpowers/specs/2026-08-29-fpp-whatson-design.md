# What's On — sports schedule display for the FPP panel

Date: 2026-08-29
Status: approved design, not yet implemented

## Purpose

A display service for the 192x192 LED panel that answers one question: *what
sport worth watching is on today and tomorrow, and what channel is it on?*

It also surfaces **highlights that have just been posted** — a condensed F1
race, a tennis match recap — as scannable QR cards, so a good event you missed
is still something you can go watch.

It is a **schedule board**, not a scoreboard. `fpp scoreboard` and `fpp nfl`
already show live scores for chosen leagues. This service surveys everything,
ranks it, and tells you where to watch — filtered so that nothing appears that
the user cannot actually watch in the USA.

Invoked on demand like the other display services. Not enabled at boot.

## Scope

In scope: a new `fpp whatson` command and `fpp-whatson.service`, the
`oddities.yaml` and `highlight_sources.yaml` seed files, YouTube highlight
discovery with QR cards, device registration, and Home Assistant wiring.

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
| Home teams | `baseball/mlb`, `hockey/nhl`, `soccer/usa.1`, `soccer/usa.nwsl`, `basketball/wnba`, `basketball/mens-college-basketball` |
| Oddity | `data/oddities.yaml` (curated windows) |

The home-team slugs are fetched only to find the user's own teams; every other
game in them is discarded. A Mariners-only MLB fetch is one request yielding at
most two cards. NFL and college football are already fetched for their own tier.

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

Two normalisation rules the home-team leagues force, both load-bearing:

- **Regional suffixes strip to the parent service.** `Prime Video-Seattle` is
  Prime Video, which the user has.
- **Bare local call signs are watchable.** `KOMO-TV`, `KING`, `KIRO` are local
  over-the-air. Without this rule the Storm game lands in the payable tier
  despite being free on an antenna.

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
- it is an **F1 Race or Sprint** session (Qual and practice do not qualify);
- it carries `major: true` (or falls after `major_from:`) in `oddities.yaml`.

A group-stage Sudamericana tie or a Tuesday darts preliminary is not major, and
so is dropped when it is on a service the user does not have.

## Home teams

Seattle teams are always shown when they play, regardless of sport, channel, or
caps. This is a deliberate exception to the channel filter, not an oversight.

Configured in `src/fpp/data/home_teams.yaml` so the list is editable without
code:

    - { slug: football/nfl,              team: Seattle Seahawks }
    - { slug: baseball/mlb,              team: Seattle Mariners }
    - { slug: hockey/nhl,                team: Seattle Kraken }
    - { slug: soccer/usa.1,              team: Seattle Sounders FC }
    - { slug: soccer/usa.nwsl,           team: Seattle Reign FC }
    - { slug: basketball/wnba,           team: Seattle Storm }
    - { slug: football/college-football, team: Washington Huskies }
    - { slug: basketball/mens-college-basketball, team: Washington Huskies }

**They bypass the channel filter entirely**, and are marked `$` when the
broadcast is payable. Where an event lists several broadcasts, the card shows
the best one available to the user: whitelisted first, then payable, and never
a foreign-only feed. On 2026-08-29 this produces `$ Mariners.TV` and `$ NWSL+`
alongside the Sounders on Apple TV and the Storm on KOMO — a board that tells
the user their teams are playing and what each would cost.

**Home games occupy their own block, placed first**, ahead of today:

    [SEATTLE][home games][TODAY][...][TOMORROW][...][AVAILABLE TO WATCH][...]

A separate block rather than pinned rows inside the day blocks, for two
reasons: it guarantees the visibility the rule promises, and it stops home games
consuming a per-sport cap — a Seahawks game should not cost an NFL slot.

Home events are **deduplicated out of the day blocks**, so a Huskies game never
appears twice. Cap of 4, ordered today before tomorrow, then by start time.

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
12s / 210s / 6s.

**Highlight cards are exempt** and hold a 15-second floor — see the dwell
exception under Highlights.

Worst case is now 4 home cards, 16 event cards, 3 highlight cards and 4
dividers. At the 6s floor with the QR exemption that is roughly 181 seconds,
which is why `--cycle` is 210 rather than 180: 6s is already the legibility
limit, so the lap budget had to grow rather than the floor shrink. If the caps
ever rise again, this is the number that breaks first.

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

## Highlights — "things you could go watch"

A separate module, `src/fpp/highlights.py`, feeding a third block of slides.
Kept out of `whatson.py` because it is a distinct source with a distinct
failure mode.

### Source

YouTube per-channel RSS: `https://www.youtube.com/feeds/videos.xml?channel_id=<id>`.
No API key and no quota, parsed with stdlib `xml.etree`.

ESPN was evaluated first and rejected: the `highlights` array on a competition
is empty, and the event `links` point at Gamecast and Preview pages rather than
video.

Two properties of the feed shape the design:

- **It is a rolling window of about 15 videos.** On a busy channel that is
  three or four days. This is a recency feature, not an archive.
- **Title matching is mandatory.** The F1 channel posts constant filler
  ("Grid Games", driver interviews). The wanted video appears only after a
  session, so sources match on title patterns, never on "newest video".

### Configuration

`src/fpp/data/highlight_sources.yaml`, one entry per source:

    - name: Formula 1
      sport: f1
      channel_id: UCB_qr75-ydFVKSF9Dmo6izg
      patterns: ["Race Highlights", "Qualifying Highlights", "Sprint Highlights"]

Seeded sources: F1 official; tennis (ATP, WTA, US Open, Wimbledon); NFL and
ESPN College Football; soccer (NBC Sports for the EPL, CBS Sports Golazo for
the UCL).

### Selection

Keep a video when it was published within the last **48 hours** and its title
matches one of its source's patterns, case-insensitively. Deduplicate by video
id. Then cap at **3 cards**, at most one per source, ranked by recency. The
per-source cap stops a single F1 weekend (race, qualifying and sprint) from
consuming the whole block.

### Placement and card

A third block, after tomorrow, behind its own `AVAILABLE TO WATCH` divider:

    [TODAY][...][TOMORROW][...][AVAILABLE TO WATCH][highlight cards]

Card layout:

    HIGHLIGHTS      2h     22px strip; shows age, not clock time
    -----------------
    ITALIAN GP             text_fit, size 14
    Race Highlights        size 12 dimmed
    [ QR code ]            132px, dark-on-white, centred

### QR encoding

`youtu.be/<VIDEOID>` is 28 bytes, which fits **QR v2 (25x25 modules) at ECC-L**,
capacity 32 bytes. At 4px per module that is 100px plus a 32px quiet zone =
132px, leaving roughly 60px for the title strip. Library: `segno` — pure
Python, no dependencies, unlike `qrcode`.

**The risk here is physical, not geometric.** Phone cameras often struggle to
scan a bright emissive LED matrix. Mitigations: render dark-on-white rather
than the panel's usual light-on-dark, keep the full quiet zone, and use 4px
modules rather than 3. **This must be physically tested on the panel before the
rest of the highlights work is built** — if a QR cannot be scanned off this
display, the whole feature needs a different handoff.

### Dwell exception

Highlight cards get a **dwell floor of 15 seconds**, exempt from the
shrink-to-fit rule that governs every other card. Other cards are glanced at; a
QR card must be noticed and then scanned with a phone. A 6-second QR card is one
nobody ever scans.

### Refresh and failure

Highlights refresh every 10 minutes, independent of the 60-second live refresh —
they do not appear that quickly.

Two limitations, stated rather than papered over:

1. **EPL highlights are frequently geo-restricted in the US**, and RSS gives no
   way to detect this. A soccer card can therefore lead to a video that will not
   play. Recorded as a comment in the config rather than silently dropping the
   source.
2. **A dead or renamed channel fails silently.** The feed 404s, that source is
   skipped, the block shrinks. No error card — a broken highlight feed must not
   cost the user the schedule board.

## Device integration

Five files in `device/`:

1. **`fpp-whatson.service`** (new), modelled on `fpp-scoreboard.service`:
   `ExecStart=/home/fpp/fpp-worldclock-venv/bin/fpp --host 127.0.0.1 whatson --interval 12 --cycle 210`,
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
- home-team matching across all eight configured entries, including that a home
  game on a non-whitelisted service still appears and is marked payable, that it
  is deduplicated out of the day blocks, and that it does not consume a
  per-sport cap;
- regional and local channel normalisation (`Prime Video-Seattle` -> Prime
  Video; `KOMO-TV` watchable);
- broadcast preference order, that a Mariners game with `Sportsnet` and `TVA`
  present shows `Mariners.TV` and never the Canadian feed;
- **the PDT day-boundary split**, including an event that is "tomorrow" in PDT
  but already the day after in UTC. This is the bug this design is most likely
  to have.

Highlight tests, against a captured YouTube RSS fixture:

- title-pattern matching, including the filler videos that must not match;
- the 48-hour recency window, including a video exactly on the boundary;
- the cap of 3 and the one-per-source rule, using an F1 weekend that posts
  race, qualifying and sprint highlights together;
- a 404 or malformed feed skips that source without failing the run;
- QR payload encodes to v2 at ECC-L and round-trips to the right video id.

Render smoke tests: every card type renders to a JPEG without exception,
including a live tennis card, a payable card, a highlight QR card, and the
empty state.

Physical test, before the rest of the highlights work: render one QR card to
the panel and confirm a phone can actually scan it.

Manual check: `fpp whatson --dry-run --out /tmp/cards` writes PNGs locally so a
real day can be eyeballed before anything touches the panel.

## New files

    src/fpp/displays/whatson.py
    src/fpp/highlights.py
    src/fpp/data/oddities.yaml
    src/fpp/data/highlight_sources.yaml
    src/fpp/data/home_teams.yaml
    device/fpp-whatson.service
    device/sudoers-fpp-whatson
    tests/test_whatson.py
    tests/test_highlights.py

## Dependencies

One addition to `pyproject.toml`: `segno`, for QR rendering. Pure Python with
no transitive dependencies. Everything else uses Pillow and the stdlib, both
already present.
