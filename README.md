# Dispatch Zero

Location-based adventure web app. Sends you on real-world missions to photograph nearby landmarks — murals, sculptures, memorials, historic buildings, churches, parks, post offices — framed as field assignments from a handler called Zero, with three selectable handler voices (pulp / spy-thriller / fantasy-ceremonial).

Runs in your phone's browser. Add to home screen for a PWA install.

**Canonical instance:** <https://dispatchzero.ataary.com>

This repository contains the full source. You're welcome to run your own instance — see [Self-hosting](#self-hosting) below.

---

## How it works

Sign up with a callsign and password (no email, no name, no phone). Pick an organization (Archive, Agency, or Guild — same character, different voice). Tap **Request Dispatch**. The app finds a real landmark near you using a tiered discovery pipeline:

1. **2 km narrow OSM** — Overpass query for art, murals, sculptures, memorials
2. **5 km narrow OSM** — same, wider radius
3. **5 km broad OSM** — adds historic buildings, places of worship, viewpoints
4. **5 km Wikipedia** — geosearch enriched with Wikidata
5. **5 km local** — places curated/imported into the instance's own database (used as a last fallback for rural-coverage gaps)

A GPT-class model writes a fresh briefing in your handler's voice. You walk to the target with a live compass. Within 80 m, the camera unlocks; you take a photo as proof. The app verifies the photo by GPS + EXIF freshness, composes a 4:5 shareable mission card, and adds the run to your dossier.

A 90-day re-entry filter prevents re-dispatching the same place to the same user too soon.

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2
- **Data:** PostgreSQL + PostGIS, Redis (rate limiting + session signal)
- **Geo data sources:** OpenStreetMap (via Overpass), Wikipedia geosearch + Wikidata, optional local-DB tier (e.g. USGS GNIS import — see `src/dispatchzero/tools/import_gnis.py`)
- **AI:** Ollama Cloud (`gpt-oss:120b` by default) — any OpenAI-compatible endpoint works; leaving the API key blank disables AI and uses deterministic placeholder text
- **Image:** Pillow for thumbnails, EXIF stripping, and mission-card composition
- **Frontend:** Vanilla HTML/CSS/JS, no SPA framework; installable as a PWA
- **Reverse proxy:** Caddy (auto-HTTPS via Let's Encrypt)
- **Container:** Docker Compose

## Self-hosting

### Local dev

```bash
git clone https://github.com/johnsonfarmsus/dispatch-zero.git
cd dispatch-zero
cp .env.example .env             # then edit — see comments in .env.example
docker compose up --build
```

App at <http://localhost:8000/healthz>.

For a first sanity check:

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test pytest
```

### Production deployment

There's a thin SSH-based deploy script for a single-VPS setup:

```bash
cp deploy/.env.local.example deploy/.env.local
# edit deploy/.env.local with your host, remote dir, healthcheck URL
./deploy/deploy.sh
```

This rsyncs the source to your VPS and runs `docker compose up -d --build` over SSH. It's intentionally minimal — designed for the maintainer's setup. Adapt freely for your own infra.

You'll need:

- A VPS with Docker + Docker Compose installed
- Ports 80/443 free (Caddy uses them)
- A DNS A record pointing your domain at the VPS
- A `.env` file on the VPS at `/opt/dispatchzero/.env` (or wherever `DZ_REMOTE_DIR` points)
- The `Caddyfile` updated to your domain name

### Rural-area data import

If your instance covers small towns where OSM and Wikipedia are sparse, the local-DB tier exists for you. There's a USGS GNIS importer at `src/dispatchzero/tools/import_gnis.py` that loads churches, cemeteries, parks, post offices, dams, bridges, towers, trails, and waterfalls into the `places` table:

```bash
docker compose exec app python -m dispatchzero.tools.import_gnis \
    --file /uploads/imports/legacy/YOUR_STATE_Features.txt \
    --counties all \
    --categories church,cemetery,park,falls,trail,dam,bridge,tower,post_office
```

**Note:** USGS removed cultural feature classes from the active GNIS dataset in 2021. You'll need a pre-2021 snapshot for those classes — the Internet Archive has them: <https://web.archive.org/web/2020*/https://geonames.usgs.gov/docs/stategaz/>

## Privacy & data model

Dispatch Zero is built with a deliberately small data footprint. Full statement at the canonical instance's `/security` page; short version:

- **Stored:** callsign, argon2id password hash, dispatches, captured photos (EXIF stripped). No email, name, phone, or device ID.
- **One cookie**, signed, used only for session. No analytics, no trackers, no ad network.
- **Location** is read only when you request a dispatch, use the compass, or capture a photo. Not retained as history.
- **Sharing** is opt-in. Share URLs use unguessable tokens; no public index.
- **What leaves the network:** briefing text → your configured AI endpoint; geodata lookups → OpenStreetMap, Wikipedia, Wikidata. Nothing else.

If you self-host, you control all of this end-to-end.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: bug reports welcome, PRs welcome with prior discussion on substantive changes, no SLA on review.

## License

[GNU Affero General Public License v3.0](LICENSE).

In plain English: you're free to use, modify, and redistribute this code. If you run a modified version as a network service, you must make the modified source available to your users. This is intentional — it keeps the project, and any derivatives, in the public commons.

If you'd like to discuss a use case the AGPL doesn't cleanly cover, open an issue.
