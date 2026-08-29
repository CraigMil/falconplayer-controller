# ESPN fixtures

Captured live on 2026-08-29 (PDT) — a deliberately rich day:

- US Open in progress (`tennis_atp`, `tennis_wta`), NCAAF opening weekend,
  the Italian GP weekend at Monza, and four Seattle teams playing.
- `facup_empty` and `nhl_empty` are genuine out-of-season responses
  (`events: []`), kept so the empty path is tested against real data.

Trimmed to stay committable: tennis keeps 2 groupings x 6 competitions per
tournament, MLB keeps the Seattle games plus two others, and per-event
`headlines`/`odds`/`leaders`/`weather`/`linescores` were dropped. Broadcast,
status, competitor and round data — everything the design reads — is intact.

Facts these fixtures encode, which the tests assert on:

| Fixture | Fact |
|---|---|
| `mlb_20260829` | Mariners on `MLB.TV`, `Mariners.TV`, `Sportsnet`, `TVA` — payable, plus Canadian feeds that must never be shown |
| `mls_20260829` | Sounders on `Apple TV` — watchable |
| `nwsl_20260829` | Reign on `NWSL+` — payable |
| `wnba_20260829` | Storm on `KOMO-TV`, `Spectrum Sports Net`, `Prime Video-Seattle` — exercises local call-sign and regional-suffix normalisation |
| `f1_monza` | One event, five sessions keyed `FP1/FP2/FP3/Qual/Race`, all `Apple TV`. **No Sprint** — the Sprint-is-major test must synthesise one |
| `tennis_atp` | US Open carries `major: true`; tournament-level default card |

Re-capture is not expected. If ESPN changes shape, capture a new dated fixture
rather than editing these — the assertions above are the point.
