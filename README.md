# Dispatch Zero

Location-based adventure web app. Sends you on real-world missions to photograph nearby landmarks — murals, sculptures, memorials, historic buildings, churches, parks, post offices — framed as field assignments from a handler called Zero, in one of three selectable voices (pulp / spy-thriller / fantasy-ceremonial).

Runs in your phone's browser. Add to home screen for a PWA install. No app store required.

**Canonical instance:** <https://dispatchzero.ataary.com>

This repository contains the full source under AGPL-3.0. You're welcome to run your own instance — see [Self-hosting](#self-hosting) below.

---

## Why

Dispatch Zero is a game built on open-source tools that contributes back to the open data it uses to power itself.

The dispatch engine draws on [OpenStreetMap](https://www.openstreetmap.org) (via Overpass), [Wikipedia](https://en.wikipedia.org) geosearch, and Wikidata to find places near you. The briefing engine runs on [OLMo 2](https://allenai.org/olmo) — open weights, open training data, Apache-2.0. The whole stack is open: PostgreSQL/PostGIS, Redis, Python/FastAPI, Pillow, vanilla HTML/CSS/JS, Caddy. No proprietary dependencies, no analytics, no trackers.

The round-trip closes the loop. When a player visits a place that *isn't* on OSM, they can report it from inside the game. The maintainer reviews each submission and pushes verified ones back to OSM as the bot account `DispatchZero` — with the original photo's GPS as the coordinates, the user-supplied description or Wikipedia link in the appropriate tags, and `source=survey;Dispatch Zero` provenance baked into every changeset. Every player walk becomes a potential improvement to the global commons that the game itself reads from.

Same logic applies to mission completions of non-OSM places (Wikipedia-sourced, community-sourced). After a player on the ground verifies one with a photo, it surfaces in the maintainer's review queue as a publish candidate.

The license enforces the philosophy: AGPL-3.0 means any fork that runs as a network service must make its modified source available to its users. The project, and any derivative, stays in the public commons.

## How it works

Sign up with a callsign and a password — no email, no name, no phone. Pick an organization (The Archive, The Agency, or The Guild — same character, different voice). Tap **Request Dispatch**. The system finds a real landmark near you, generates a fresh in-voice briefing, and sends you walking.

When you're within 80 m of the target, the camera unlocks. You take a photo as proof. The app verifies the photo by GPS + EXIF freshness, composes a 4:5 shareable mission card, and adds the run to your dossier.

### Discovery

Six-tier search, evaluated in order until at least one eligible candidate surfaces:

1. **Caller radius, strict OSM** (typically 2 km) — Overpass for the art-first set: murals, sculptures, statues, monuments, memorials, historic buildings, viewpoints. These are what we want users to find *first*.
2. **5 km strict OSM** — same art-first filters, wider radius.
3. **5 km broad OSM** — adds the everyday-landmark layer: churches (`amenity=place_of_worship`), post offices, libraries, town halls, cemeteries, fountains, lighthouses, windmills, towers, peaks, waterfalls, parks. Liberal name-required filtering keeps the noise out.
4. **5 km Wikipedia** — geosearch enriched with Wikidata. Catches encyclopedia-listed places OSM hasn't surfaced.
5. **10 km broad OSM** — one wider OSM sweep before falling to local data. Catches semi-rural towns where the 5 km tiers came up empty.
6. **10 km local DB** — community submissions approved through the in-game review queue. This is the closed-loop tier: places players reported, the maintainer approved, and that haven't yet been pushed upstream to OSM (or that the maintainer chose to keep local-only).

The strict-first bias preserves the game's character. A user in an art-rich town gets murals before they get a post office.

A 30-day re-entry filter prevents re-dispatching the same place to the same user too soon. When that does cycle back, the briefing is force-generated fresh with follow-up framing ("secondary sweep", "the file is reopened", style-appropriate per organization) so re-visits don't feel like reruns. Per-user permanent exclusions let users report a place as gone / inaccessible / never findable; reported places never come up for that user again, and two distinct users reporting the same place flags it for the maintainer to review.

### Verification

The capture screen requires a GPS fix within 80 m of the target. The uploaded photo's EXIF DateTimeOriginal must be recent (default 10-minute window) to confirm it was taken at the location, not pulled from a camera roll. Failed verifications are surfaced in-character, not as form errors.

### Community submissions and the OSM round-trip

Any logged-in player can submit a point of interest from the in-game **Report** screen: photo + name + category + optional description + optional link. GPS comes from the browser's geolocation (not the photo's EXIF), so users don't have to enable Location for their iOS Camera. The submission lands as a pending row in the maintainer's review queue with a freshly composed `PENDING` contribution card.

In the queue, the maintainer sees:

- The photo and place metadata.
- A clickable OpenStreetMap link at zoom 19 — the ground-truth verification tool.
- An **OSM pre-flight check** badge: a background Overpass query runs after every submission to look for nearby OSM nodes at the same category, surfacing matches with distance + clickable links. Advisory only — never blocks an action.
- Submitter callsign + adventure-style for context.
- Three actions: **Approve** (place becomes active locally), **Submit to OSM** (publish a node to OSM as the DispatchZero bot account and stamp it active locally), **Return** (with an optional note that shows up on the submitter's dossier card).

Mission completions at places that *didn't* come from OSM (Wikipedia, community, internal) also surface as **publish candidates** in the same queue, with a `WIKIPEDIA` / `COMMUNITY` source badge. Actions are **Submit to OSM** or **Skip**. Wikipedia-sourced candidates auto-derive the `wikipedia=` tag from the article title at publish time.

OSM publishing safety:

- **Connect-once OAuth 2.0** flow with token refresh. The maintainer's bot account credentials live in a single-row table; the per-request flow never re-prompts.
- **Dry-run mode** (env-toggled) builds the changeset XML and logs it but doesn't POST. Lets the maintainer verify the round-trip end-to-end before any real edit lands.
- **Daily cap** on real publishes (default 5/day) keeps the bot from looking like a bulk-import operation OSM admins would flag.
- **Dedup** on `places.osm_published_node_id` — the same place can't be pushed twice, even across re-submissions.
- **Subtype picker** for ambiguous categories (`historic`, `infrastructure`) — the maintainer picks the specific OSM tag bundle (bridge / tower / dam / etc.) before the publish runs.
- Every changeset includes `source=survey;Dispatch Zero` and `created_by=Dispatch Zero/0.1` so OSM mappers can identify our edits at a glance.

The full audit trail (every dry-run XML payload + every real publish's changeset/node IDs + which admin approved it) lives in the `osm_publications` table.

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2
- **Data:** PostgreSQL + PostGIS, Redis (rate limiting + ephemeral state)
- **Geo data sources:** OpenStreetMap (via Overpass — read AND write through the bot account), Wikipedia geosearch + Wikidata
- **AI:** [Ollama](https://ollama.com) running [OLMo 2](https://allenai.org/olmo) 13B by default. Any OpenAI-compatible chat endpoint works — Ollama Cloud (paid, `gemma4:31b-cloud`) is documented as an alternative for fork users without local GPU resources. The canonical instance runs Ollama on a separate inference box reached over Tailscale.
- **OSM integration:** OAuth 2.0 bot account, Overpass for reads, OSM Editing API 0.6 for writes (changeset + osmChange XML)
- **Image:** Pillow for thumbnails, EXIF stripping, mission-card composition, and contribution-card status stamping
- **Frontend:** Vanilla HTML/CSS/JS, no SPA framework; installable as a PWA
- **Reverse proxy:** Caddy (auto-HTTPS via Let's Encrypt)
- **Container:** Docker Compose

## Self-hosting

### Prerequisites for local dev

You need a working Ollama on your host machine with `olmo2:13b` pulled. ~15 minutes one-time setup:

```bash
# Install Ollama — see https://ollama.com/download for your OS
# (macOS Homebrew):
brew install ollama

# Pull the model (~8 GB)
ollama pull olmo2:13b

# Ollama auto-starts as a service after install — verify:
ollama list
```

If you'd rather skip the local-model step (you don't have ~10 GB free or you don't want a model resident in memory), see *Cloud fallback* below.

### Local dev

```bash
git clone https://github.com/johnsonfarmsus/dispatch-zero.git
cd dispatch-zero
cp .env.example .env             # the defaults work; edit if you want
git config core.hooksPath .githooks   # one-time, install repo hooks
docker compose up --build
```

App at <http://localhost:8000/healthz>.

The app container reaches your host's Ollama at `http://host.docker.internal:11434/v1` (the default in `.env.example`). The compose file declares an `extra_hosts` entry so this resolves on Linux too, not just Docker Desktop.

Run the test suite:

```bash
./deploy/test.sh                              # if you have DZ_VPS_HOST set
# or, directly via docker compose:
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test pytest
```

### Cloud fallback (skip the local model)

Open `.env`, comment the four `OLLAMA_*` lines under the default block, and uncomment the four under "Alternative: Ollama Cloud". Get an API key at <https://ollama.com>. Briefings will route to `gemma4:31b-cloud` over the hosted endpoint instead of your local Ollama. No other changes needed; the rest of the stack is identical.

### OSM bot account (for the round-trip)

To run the round-trip (publish approved submissions back to OSM), you need an OSM account and an OAuth 2.0 application:

1. Create a dedicated OSM account for the bot (recommended over your personal account — keeps reputation siloed). Verify the email.
2. Register an OAuth 2.0 application at <https://www.openstreetmap.org/oauth2/applications/new>:
   - **Redirect URI:** `https://YOUR-DOMAIN/admin/osm/callback`
   - **Confidential application:** yes
   - **Permissions:** `Read user preferences` + `Modify the map` only. Skip the rest — over-scoped apps draw OSM admin scrutiny.
3. OSM gives you a Client ID and Client Secret. Drop them into your instance's `.env`:
   ```
   OSM_CLIENT_ID=...
   OSM_CLIENT_SECRET=...
   OSM_DRY_RUN=true
   ```
4. Restart the app. In the in-game Settings, the admin (a user flipped to `is_admin=true` via the CLI) gets an "Admin" link. The review queue shows a `Connect OSM` prompt — click it, authorize, return.
5. With `OSM_DRY_RUN=true`, the publish path builds the changeset XML and logs it but skips the HTTP call to OSM. Eyeball a few dry-run outputs in the app logs before flipping `OSM_DRY_RUN=false` and going live.

To promote a user to admin:

```bash
docker compose exec app python -m dispatchzero.tools.user_admin promote <callsign>
```

### Production deployment

Thin SSH-based deploy for a single-VPS setup:

```bash
cp deploy/.env.local.example deploy/.env.local
# edit deploy/.env.local with your VPS host, remote dir, healthcheck URL
./deploy/deploy.sh
```

This rsyncs the source to your VPS (with `--exclude 'uploads'` to protect captured user photos — see the comment block in `deploy/deploy.sh` for *why* this matters) and runs `docker compose up -d --build` over SSH.

You'll need:

- A VPS with Docker + Docker Compose installed
- Ports 80/443 free (Caddy uses them)
- A DNS A record pointing your domain at the VPS
- A `.env` file on the VPS at `/opt/dispatchzero/.env` (or wherever `DZ_REMOTE_DIR` points)
- The `Caddyfile` updated to your domain name
- Either a local Ollama on the VPS, an Ollama on a separate machine reachable from the VPS (the canonical instance uses Tailscale for this), or the cloud-fallback config

### Optional: legacy rural-data import

If you're running an instance in an area where OSM coverage is genuinely sparse and you want a starting fallback layer before users have generated community submissions, a [USGS GNIS importer](src/dispatchzero/tools/import_gnis.py) is included. It loads named features (churches, cemeteries, parks, post offices, dams, bridges, towers, trails, waterfalls) into the local-DB tier:

```bash
docker compose exec app python -m dispatchzero.tools.import_gnis \
    --file /uploads/imports/legacy/YOUR_STATE_Features.txt \
    --counties all \
    --categories church,cemetery,park,falls,trail,dam,bridge,tower,post_office
```

The canonical instance ran this for the entire state of Washington at one point — ~6,700 places — then retired the import after the broad-tier OSM expansion absorbed equivalent coverage with better tag quality. The importer is kept around because the trade-off may go the other way for your area: places OSM doesn't have yet but GNIS does, especially in the western US where GNIS is dense.

**Note:** USGS removed cultural feature classes from the active GNIS dataset in 2021. For those classes you need a pre-2021 snapshot — the Internet Archive has them: <https://web.archive.org/web/2020*/https://geonames.usgs.gov/docs/stategaz/>

## Privacy & data model

Dispatch Zero is built with a deliberately small data footprint. Full statement at the canonical instance's [`/security`](https://dispatchzero.ataary.com/security) page; short version:

- **Stored:** callsign, argon2id password hash, dispatches, captured photos (EXIF stripped). No email, name, phone, or device ID.
- **One cookie**, signed, used only for session. No analytics, no trackers, no ad network.
- **Location** is read only when you request a dispatch, use the compass, capture a photo, or submit a community POI. Not retained as history.
- **Sharing** is opt-in. Share URLs use unguessable tokens; no public index. Both mission completions and approved community submissions can be shared.
- **What leaves your network:** briefing text → your configured AI endpoint (your local Ollama by default, never leaves your machine); geodata lookups → OpenStreetMap, Wikipedia, Wikidata; OSM publications (only when an admin approves them) → OSM Editing API as the configured bot account. Nothing else.

If you self-host with local Ollama, the entire briefing pipeline stays inside your network. The geo lookups (read) and OSM publications (write) are inherently networked — they're the round-trip.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: bug reports welcome, PRs welcome with prior discussion on substantive changes, no SLA on review.

After cloning, install the repo's git hooks once:

```bash
git config core.hooksPath .githooks
```

The pre-commit hook blocks commits to `deploy/*.sh` that would re-introduce a data-loss bug we hit on 2026-06-02 (rsync `--delete` without `--exclude 'uploads'` silently wiped captured user photos on the VPS).

## License

[GNU Affero General Public License v3.0](LICENSE).

In plain English: you're free to use, modify, and redistribute this code. If you run a modified version as a network service, you must make the modified source available to your users. This is intentional — it keeps the project, and any derivatives, in the public commons.

If you'd like to discuss a use case the AGPL doesn't cleanly cover, open an issue.
