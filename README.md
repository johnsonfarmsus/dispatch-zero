# Dispatch Zero

Location-based adventure web app. Sends you on real-world missions to photograph nearby landmarks — murals, sculptures, memorials, historic buildings, churches, parks, post offices — framed as field assignments from a handler called Zero, in one of three selectable voices (pulp / spy-thriller / fantasy-ceremonial).

Runs in your phone's browser. Add to home screen for a PWA install. No app store required.

**Canonical instance:** <https://dispatchzero.ataary.com>

This repository contains the full source under AGPL-3.0. You're welcome to run your own instance — see [Self-hosting](#self-hosting) below.

---

## How it works

Sign up with a callsign and a password — no email, no name, no phone. Pick an organization (The Archive, The Agency, or The Guild — same character, different voice). Tap **Request Dispatch**. The system finds a real landmark near you, generates a fresh in-voice briefing, and sends you walking.

When you're within 80 m of the target, the camera unlocks. You take a photo as proof. The app verifies the photo by GPS + EXIF freshness, composes a 4:5 shareable mission card, and adds the run to your dossier.

### Discovery

Five-tier search, evaluated in order until at least one eligible candidate surfaces:

1. **2 km narrow OSM** — Overpass query for art, murals, sculptures, memorials
2. **5 km narrow OSM** — same, wider radius
3. **5 km broad OSM** — adds historic buildings, places of worship, viewpoints
4. **5 km Wikipedia** — geosearch enriched with Wikidata
5. **5 km local DB** — places curated/imported into the instance's own database (USGS GNIS imports, manual additions). The rural-coverage fallback.

A 30-day re-entry filter prevents re-dispatching the same place to the same user too soon. When that does cycle back, the briefing is force-generated fresh with follow-up framing ("secondary sweep", "the file is reopened", style-appropriate per organization) so re-visits don't feel like reruns. Per-user permanent exclusions let users report a place as gone / inaccessible / never findable; reported places never come up for that user again, and two distinct users reporting the same place flags it for the maintainer to review.

### Verification

The capture screen requires a GPS fix within 80 m of the target. The uploaded photo's EXIF DateTimeOriginal must be recent (default 10-minute window) to confirm it was taken at the location, not pulled from a camera roll. Failed verifications are surfaced in-character, not as form errors.

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2
- **Data:** PostgreSQL + PostGIS, Redis (rate limiting + ephemeral state)
- **Geo data sources:** OpenStreetMap (via Overpass), Wikipedia geosearch + Wikidata, optional local-DB tier populated by the included [USGS GNIS importer](src/dispatchzero/tools/import_gnis.py)
- **AI:** [Ollama](https://ollama.com) running [OLMo 2](https://allenai.org/olmo) 13B by default. Any OpenAI-compatible chat endpoint works — Ollama Cloud (paid) is documented as an alternative for fork users without local GPU resources. The canonical instance runs Ollama on a separate inference box reached over Tailscale.
- **Image:** Pillow for thumbnails, EXIF stripping, and mission-card composition
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

### Rural-area data import

If your instance covers small towns where OSM and Wikipedia are sparse, the local-DB tier exists for you. There's a [USGS GNIS importer](src/dispatchzero/tools/import_gnis.py) that loads churches, cemeteries, parks, post offices, dams, bridges, towers, trails, and waterfalls into the `places` table:

```bash
docker compose exec app python -m dispatchzero.tools.import_gnis \
    --file /uploads/imports/legacy/YOUR_STATE_Features.txt \
    --counties all \
    --categories church,cemetery,park,falls,trail,dam,bridge,tower,post_office
```

**Note:** USGS removed cultural feature classes from the active GNIS dataset in 2021. For those classes you need a pre-2021 snapshot — the Internet Archive has them: <https://web.archive.org/web/2020*/https://geonames.usgs.gov/docs/stategaz/>

The canonical instance was bootstrapped with the March 2020 Washington snapshot. Statewide import in that mode yields ~6,700 places across the 9 supported categories.

## Privacy & data model

Dispatch Zero is built with a deliberately small data footprint. Full statement at the canonical instance's [`/security`](https://dispatchzero.ataary.com/security) page; short version:

- **Stored:** callsign, argon2id password hash, dispatches, captured photos (EXIF stripped). No email, name, phone, or device ID.
- **One cookie**, signed, used only for session. No analytics, no trackers, no ad network.
- **Location** is read only when you request a dispatch, use the compass, or capture a photo. Not retained as history.
- **Sharing** is opt-in. Share URLs use unguessable tokens; no public index.
- **What leaves your network:** briefing text → your configured AI endpoint (your local Ollama by default, never leaves your machine); geodata lookups → OpenStreetMap, Wikipedia, Wikidata. Nothing else.

If you self-host with local Ollama, the entire briefing pipeline stays inside your network.

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
