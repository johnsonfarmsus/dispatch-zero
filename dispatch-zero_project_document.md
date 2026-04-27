# Dispatch Zero — Comprehensive Project Document

*Version 4.0 — April 2026*

---

## Executive Summary

This document describes the product vision, technical architecture, game systems, narrative framework, and implementation decisions for **Dispatch Zero** — a location-based adventure quest web application. The product sends users on short real-world missions to photograph murals, sculptures, monuments, memorials, and historic places near them, framed as field assignments dispatched by a mysterious handler known only as Zero.

Users complete missions, earn rewards, rate both the location and the mission separately, and build a personal map of completed adventures. The product is designed to feel slightly mysterious, slightly unsettling, and just ambiguous enough that users are never entirely sure whether the organization they work for is benevolent or not.

The app launches as a web-first experience hosted on an existing Hetzner VPS (VPS 2, `89.167.39.152`), using Python with FastAPI, PostgreSQL with PostGIS, public OpenStreetMap-based services for geodata, and a self-hosted open-source text-to-speech layer for handler voices. Total operational cost is approximately $20/month — VPS 2 is sunk cost, with the only paid line being Ollama Cloud.

---

## Product Vision

### Concept

Users open the app, request a mission, and are assigned a nearby real-world destination. The destination is always based on real map data and is framed as a field assignment from Zero — an unseen handler whose identity, allegiance, and true purpose are never fully revealed. The user travels there, photographs it from within the app, and receives confirmation and debrief from Zero.

### Core Promise

The product exists to get people out of the house for small, low-friction adventures. It transforms local discovery into a narrative loop:

- Receive a dispatch from Zero.
- Go somewhere real.
- Gather photographic proof.
- Return the report.
- Earn recognition.

### Emotional Tone

The product should feel:

- Slightly mysterious and slightly unsettling.
- Playful but not childish.
- Stylish rather than comedic.
- Ambiguous enough that users are never entirely sure whether Zero and the organization they work for is noble, manipulative, or something else entirely.

---

## Product Name and URL

**Product name:** Dispatch Zero

**Working URL:** `dispatchzero.ataary.com`

The subdomain points to VPS 2 (`89.167.39.152`). Caddy handles SSL automatically via Let's Encrypt. No new domain registration is required for launch.

**Future domain:** A dedicated `.quest` domain will be selected when the product is ready. Strong candidates include `null.quest`, `cipher.quest`, and `echo.quest`. The move requires only a DNS change and redirect — no code changes.

### Name Layers

The name **Dispatch Zero** works on two levels:

- **Before the user knows:** Dispatch Zero reads as their first dispatch — mission number zero, the beginning of their field career.
- **After the user knows:** Dispatch Zero is a dispatch *from* Zero — the handler behind everything. The name reveals itself as the player goes deeper.

---

## The Handler: Zero

Zero is the single handler designation shared across all three adventure styles. Zero manifests with a different voice, tone, and personality per style — but always uses the same name.

### Why One Name Across Three Styles

Users who encounter the product across styles, or who switch styles, will notice Zero appears in all of them. This raises the question: is Zero one person, three people, or something else entirely? That ambiguity is intentional and valuable. It is the central piece of lore the product owns.

### Handler Rules

- Zero has no visible biography.
- Zero's avatar should be obscured — silhouette, heavy shadow, partial framing. Never a clear face.
- Zero's language should remain slightly off-kilter, leaving it permanently ambiguous whether the organization is ultimately benevolent or not.
- Zero signs off differently in each style.

### Zero's Sign-Offs Per Style

| Style | Sign-off |
|---|---|
| Pulp Adventure | `— Zero. Do be careful.` |
| Secret Agency | `— Zero` |
| Fantasy Guild | `— Zero. The matter is noted.` |

The handler is always Zero across all three styles. Sign-off phrasing varies stylistically but the signature itself is identical. There is no Vale, no Ashford, no Warden — the unified name is the point.

### Handler Avatars

Avatars should be created using existing Mistral Medium / Flux credits. Visual direction:

- **Zero (Agency style):** Extreme side lighting, face half in shadow, clinical environment. No visible eyes. Sharp tailoring. Surveillance feeling.
- **Zero (Pulp style):** Backlit by a bright window, warm silhouette, maps and books visible. An impression of a person rather than a portrait.
- **Zero (Guild style):** Hooded or heavily shadowed. Stone or ancient wood behind them. No clearly definable age, gender, or era.

All three should feel like they are being viewed through frosted glass or inadequate lighting — present but unknowable. The visual consistency across three styles subtly suggests they may all be connected to something larger.

### Handler Voices

Each style has a distinct Zero voice delivered via Kokoro-82M TTS, self-hosted on VPS 2.

| Style | Voice Direction |
|---|---|
| Pulp | Warm, fast-thinking, lightly enthusiastic |
| Agency | Cold, clipped, restrained |
| Guild | Slow, resonant, formal |

Audio is generated server-side when missions are created and cached as files. The same mission briefing is never synthesized twice.

---

## Narrative Framework

### Adventure Styles

Users choose one of three narrative styles during onboarding. This controls presentation, copy, Zero's voice, faction framing, UI tone, map style, and badge labels. It does not change progression systems, data, place logic, or user history. Styles can be changed at any time without losing progress.

| Style | Organization | Tone |
|---|---|---|
| **Pulp Adventure** | The Archive | Globe-trotting, relic-hunting, expedition energy. Warm and curious but reckless. |
| **Secret Agency** | The Agency | Cold, controlled, professional, vaguely threatening. Briefings feel classified. |
| **Fantasy Guild** | The Guild | Ancient, formal, cryptic. Feels ceremonial and faintly unsettling. |

### What the Style Layer Controls

- Zero's voice, tone, and sign-off.
- Mission briefing language and framing.
- Organization name and implied lore.
- Badge names and descriptions.
- UI accent palette and icon style.
- Map tile style.

### What the Style Layer Does Not Control

- Place selection and ranking logic.
- Completion count and weekly activity counter.
- Completion state and user history.
- Backend data model.



## Visual Direction

### Primary Aesthetic Reference

The broad visual reference is the 1985/1990 **Carmen Sandiego** game lineage, adapted for modern mobile web browsers. The app should feel like an intelligence dossier and field-operations console rather than a conventional mobile game UI.

### Core Aesthetic Principles

- The interface should feel like filed intelligence, not playful app chrome.
- Surfaces should be dark, warm, and restrained rather than glossy or futuristic.
- Information should be laid out like documents, instrument readouts, and mission panels.
- Color should be sparse and intentional, with one accent color per adventure style.
- The UI should be mysterious, disciplined, and legible at a glance while walking.

### Mobile-First Interpretation

Dispatch Zero is designed for modern mobile web browsers first. The visual system must therefore preserve the Carmen Sandiego dossier feeling while respecting phone ergonomics and single-screen interaction.

Key mobile rules:

- No vertical scrolling inside core gameplay screens.
- Every gameplay screen must fit entirely within one viewport.
- Additional information lives on separate screens, not below the fold.
- Primary controls should remain in the natural thumb zone.
- Large decorative artwork is optional and should never displace high-value information.

### Broad UI Feel

The product should feel like:

- A field dossier opened on a secure device.
- A compact operations console.
- A transmission system where each screen is a complete state.
- A game with discipline and atmosphere, not a modern bloated app.

### Visual Language

- Small handler identifier in the header, not a large portrait by default.
- Condensed or operational display typography for labels, codes, and headings.
- Serif or highly readable body typography for longer briefing documents.
- Monospaced typography for mission codes, distance, bearings, timestamps, and file metadata.
- Thin rules, boxed zones, and restrained separators rather than cards everywhere.

### Color Strategy

Base palette across all styles:

- Warm charcoal or near-black backgrounds.
- Warm off-white primary text.
- Muted secondary text.
- One accent color per style.

Per-style accents:

| Style | Accent Direction |
|---|---|
| Pulp Adventure | Warm amber / brass |
| Secret Agency | Cold cyan / surveillance blue |
| Fantasy Guild | Deep moss / archival green |

Accent color should be used sparingly on mission codes, active indicators, key labels, and primary controls. The app should not rely on gradients, glowing effects, or candy-color UI.

---

## Platform Strategy

### Web First

The product launches as a mobile-first web application, installable as a PWA where supported. A native app is a future option only.

### Permissions Strategy

- **Geolocation** is requested only when the user starts a mission or captures photo proof. Never on page load.
- **Camera** is requested only at the proof capture step.

---

## Core Game Loop

1. User opens the Home screen, their base of operations.
2. User reviews identity, stats, and recent history.
3. User requests a mission.
4. User shares current location or enters ZIP code.
5. System finds nearby eligible places.
6. System filters out places the user has already completed.
7. AI selects the best candidate and writes the mission briefing in the user's chosen style.
8. User is shown a Dispatch screen with a short 2–3 line mission summary.
9. User may open the Full Brief screen for the complete mission document.
10. User accepts the mission.
11. Transit mode activates and the compass becomes the primary mission interface.
12. User travels to the destination.
13. User captures a photo inside the app.
14. System verifies completion by checking capture geolocation against target coordinates.
15. Zero confirms receipt and issues debrief in style-appropriate voice.
16. User earns points, streak progress, and badge credit.
17. User rates the location and the mission separately.
18. User may share the completed quest to Bluesky or Mastodon.
19. User returns to the Home screen with updated stats and recent history.

---



## Mobile Screen Architecture

### Core Principle

Dispatch Zero is a no-scroll gameplay experience. Every gameplay screen must fit within a single mobile viewport. If additional information or tools are needed, they appear on separate screens rather than below the fold.

### Why This Matters

This preserves the dossier-and-console feeling, improves legibility while walking, and creates a stronger sense that each mission phase is a distinct operational state rather than part of a generic app feed.

### Screen Model

Each screen should be:

- A complete moment.
- Legible at a glance.
- Limited to one primary purpose.
- Navigated screen-to-screen rather than scrolled through.

### Core Screen Sequence

| # | Screen | Purpose |
|---|---|---|
| 1 | Home | Base of operations. User identity, stats, recent mission history, request mission. |
| 2 | Dispatch | Short mission summary, small handler identifier, distance/bearing preview, accept or open brief. |
| 3 | Full Brief | Complete mission document with all details. Separate screen, no scrolling in core flow. |
| 4 | Objective | Visual confirmation of destination, category, and distance. |
| 5 | Transit | Active mission state with live compass and distance readout. |
| 6 | Capture | In-app camera proof capture. |
| 7 | Verification | Short verification state, usually auto-advancing. |
| 8 | Debrief | Mission completion confirmation, Zero response, badge or milestone callout if any. |
| 9 | Rating | Independent location and mission rating. |

### Home Screen (Screen 1)

The Home screen is the true main game screen. It functions as base of operations and the default state the user returns to between missions.

It should include:

- User display name or callsign.
- Total completions count (per-category breakdown available on a separate screen).
- Missions this week.
- Recent mission history in compact dossier form.
- A clear `Request Dispatch` button as the primary action.

This screen should feel like a mission terminal, not a dashboard packed with widgets.

### Dispatch Screen (Screen 2)

The Dispatch screen presents the offered mission before activation.

It should include:

- Small handler identifier in the upper-left, not a large portrait.
- Mission code or ID in the header.
- A 2–3 line mission summary only.
- A preview of distance and bearing.
- Optional compact user stats in the lower information zone.
- Two actions: `Open Brief` and `Accept`.

The Dispatch screen is a fast read. It is the spoken summary, not the full file.

### Full Brief Screen (Screen 3)

The Full Brief contains the complete mission text and details on a dedicated screen. It exists so richer mission writing can be preserved without introducing scrolling into the main action screens.

It should feel like opening the dossier file itself:

- Full text presentation.
- Document-like layout.
- Mission metadata header and footer.
- Minimal visual clutter.
- A single confirmation action such as `Acknowledged` or `Continue`.

### Transit and Utility Screens

The Transit screen is the active mission state after acceptance. The compass becomes live only after the mission is accepted.

Utility views such as map, clue review, or brief review should exist as separate screens or lightweight overlays, never as scroll regions appended to the main mission screen.

### Screen Layout Guidance

General screen layout priorities:

- Header row for identity, mission code, or state.
- Central content zone for the one thing the user must understand.
- Lower operational zone for status, distance, or secondary mission data.
- Bottom action row for the next decision.

### Handler Avatar Rule

The handler avatar should usually be small and functional — more like a sender marker than a portrait. A large hero-style avatar is not the default pattern. Small scale strengthens the mystery and preserves space for more useful operational information.

### Writing Constraint

The short Dispatch summary is separate from the Full Brief by design:

- **Dispatch summary:** 2–3 lines maximum.
- **Full Brief:** complete details on its own screen.

This preserves both atmosphere and usability.

---

## Mission Length Tiers

| Tier | Stops | Notes |
|---|---|---|
| **Scout** | 1 | Default v1 mission type. Fast, low-friction. |
| **Recon** | 2 | Medium outing. Multi-stop with user-chosen order. |
| **Expedition** | 3+ | Long-form adventure. Later versions only. |

Multi-stop missions do not require a fixed completion order. Users complete stops in any sequence. The mission completes when all stops are verified regardless of order.

V1 launches with Scout missions only. The data model supports multi-stop from day one.

---

## Place Categories

| Priority | Category | Notes |
|---|---|---|
| 1 | Murals / Street Art | Best visual payoff, richest story material. |
| 2 | Sculptures / Statues | Named subjects, good photography targets. |
| 3 | Memorials / Monuments | Historical weight, easy mission framing. |
| 4 | Historic Places | Strong when context is available. |
| 5 | Viewpoints | Fallback only when other categories are sparse. |

---

## Place Discovery Pipeline

The system never invents a destination. Every mission is built from real geographic data.

1. Convert user location or ZIP to coordinates via Nominatim or Photon.
2. Query nearby places via Overpass API using approved OSM tags.
3. Normalize results into the internal place schema.
4. Enrich top candidates with available descriptive context from Wikipedia/Wikidata.
5. Score candidates for quest-worthiness.
6. Filter out places the user has already completed.
7. Prefer validated mission library entries when available.
8. If no validated mission exists, generate a fresh one via AI.

### Quest-Worthiness Scoring Factors

- Place has a name.
- Place has artistic, commemorative, or historical context.
- Place is publicly accessible.
- Place has been positively rated before.
- Place has a high completion rate.
- Place has not been flagged as unsafe, inaccessible, or gone.
- Place has not been completed by the requesting user.

---

## Mission Library and Rating System

### Library Logic

Good missions are saved and reused. Location quality and mission quality are tracked independently because they are independent failure modes.

### Two-Axis Rating System

After completion, the user rates two things separately with thumbs up/down:

- **Location** — Was this a good real-world destination?
- **Mission** — Was the briefing text interesting and well-written?

| Location | Mission | Action |
|---|---|---|
| 👍 | 👍 | Save both. Reuse mission as-is for future users. |
| 👍 | 👎 | Keep place. Flag mission for AI regeneration. |
| 👎 | 👍 | Flag or retire place. Discard mission. |
| 👎 | 👎 | Flag or retire place. Discard mission. |

### Negative Location Reasons (one-tap optional)

- Place is gone
- Couldn't find it
- Not accessible
- Felt unsafe

### Implicit Signal

A submitted verified photo without a rating counts as a soft positive for the location and neutral for the mission.

### No Repeat Locations

Every user has a completed-place history. The system filters out completed places at candidate selection time, before scoring. A user is never sent to the same location twice.

---

## Photo Verification

### Capture Mechanism: Native Camera Intent (Path 1)

Photo capture uses the OS-native camera via `<input type="file" accept="image/*" capture="environment">`. This:

- Launches the device camera directly on iOS (gallery selection effectively blocked) and on Android (default behavior on most browsers/launchers).
- Causes the captured photo to **auto-save to the user's camera roll / gallery** as a side effect of OS camera invocation. The user retains a personal copy of every mission photo with no extra action.
- Hands the file back to the app for upload and verification.

A custom in-app camera (`getUserMedia`) is explicitly **not** used in v1. The dossier UI lives around the capture moment (review, submission, debrief), not during the shutter press.

### Primary Verification: Geolocation at Capture Time

Verification is GPS-based. The client captures device GPS at submission time and sends `(lat, lng, accuracy_m)` alongside the photo. The server checks whether the device was within the mission's configured radius of the target coordinates.

GPS, not the photo, is the proof. Why:

- Cheaper than image analysis — no AI call required.
- Faster — verification is instant.
- More reliable — no false rejects due to bad framing or lighting.
- Harder to fake casually — GPS spoofing requires deliberate effort.

### Secondary Check: Capture Freshness via EXIF

Before stripping EXIF for storage, the server reads `DateTimeOriginal`. If the photo's capture timestamp is within ~10 minutes of upload, it is treated as a fresh capture. If older, or missing entirely (typical of screenshots and processed images), the submission is rejected and Zero asks for a fresh photo in character.

This is a soft discipline check, not a security control — a determined user can rewrite EXIF. It exists to catch casual gallery-picking, not to defeat motivated cheating. The 10-minute window absorbs slow connectivity, GPS settling, and walking to find signal after capture.

### Verification Radius

Radius is configurable by place category. Smaller for precise targets like sculptures, wider for large murals or historic buildings. Urban GPS drift of 10–30 meters is accounted for in the radius setting.

### If Verification Fails

Zero asks for reconfirmation in character. The user is never shown a technical error — they receive a handler message appropriate to the style. No override button exists. The user does not know whether GPS, freshness, or both failed; the mystery is preserved.

### Audit Logging

The Completion record captures `had_exif`, `exif_datetime_delta_seconds`, and `had_exif_gps` at receipt — costs nothing to store, provides forensic signal if abuse patterns ever surface. Personal EXIF data itself (GPS, device fingerprint) is never persisted.

### Future Option: Vision Enrichment

A multimodal model may be used in later versions for debrief enrichment — describing what the submitted photo shows to generate a more personalized handler response — rather than for verification.

---

## Navigation and Map Display

### Primary: Direction Indicator

A compass-style arrow pointing toward the destination with distance shown. The default and preferred navigation mode. Keeps the experience game-like and mission-focused.

### Secondary: Map View

Revealed on user request. Minimal — two markers only (user position and destination), no search, no layer controls, no routing.

### Map Stack

- **Leaflet.js** — map rendering library, free and open source.
- **CartoDB tiles** — free, no API key, production-appropriate.
- **Custom SVG markers** — one per style, inline, no external dependency.

### Map Style Per Adventure Style

| Style | Tile | Feel |
|---|---|---|
| Pulp Adventure | CartoDB Voyager | Warm, full-detail, explorer's map |
| Secret Agency | CartoDB Dark Matter | Black, minimal, surveillance map |
| Fantasy Guild | CartoDB Positron | Soft, pale, old-world cartography |

### Swap Path

If CartoDB tiles become unavailable or paid, the replacement is a single tile URL change in Leaflet. Long-term self-hosted fallback is Protomaps PMTiles on Cloudflare R2 with MapLibre GL JS.

---

## Progression System

### Completions, Not Points

Progression is tracked as a count of verified completions, not abstract "experience points." A user has completed N places, with breakdown available per category (murals documented, sculptures documented, etc.). No XP, no levels, no rank ladder. Each location counts once toward the total — the 90-day re-entry rule allows the same location to count again later, but at any given moment a user's profile shows distinct places visited.

This was simplified from an earlier XP/rank design — the count is more honest about what the user actually did, and a "ranks unlocked" gating system added complexity without changing behavior we wanted.

### Weekly Activity

A separate "missions this week" counter shows recent activity, encouraging without being coercive (no daily-streak cliff). Resets Monday 00:00 UTC.

### Badge Philosophy

Badges reward meaningful real behaviors, not arbitrary milestones. Examples:

- First morning mission
- First night mission
- Three murals documented
- Five missions in one ZIP code
- Seven-day streak
- Long-distance mission completion

Badge names are re-skinned per style.

---

## Social Sharing

**Supported platforms:** Bluesky and Mastodon only. No major commercial social platforms.

**V1 implementation:** Pre-filled share links. No OAuth, no API keys, no backend work required. User reviews and posts manually.

**Future:** Full AT Protocol posting for Bluesky in Phase 2.

---

## Technical Stack

### Core

| Layer | Tool |
|---|---|
| Language | Python |
| Framework | FastAPI |
| Database | PostgreSQL + PostGIS |
| Cache | Redis |
| Reverse proxy / HTTPS | Caddy |
| Deployment | Docker Compose |

### AI and Media

| Function | Tool |
|---|---|
| Mission writing | Ollama Cloud (~$20/month flat rate) |
| Future image enrichment | Ollama Cloud multimodal model |
| Handler TTS | Kokoro-82M (self-hosted on VPS 2) |
| Handler avatar art | Mistral Medium / Flux (existing credits) |

### Geodata

| Function | Tool |
|---|---|
| Geocoding | Public Nominatim (cached aggressively) |
| Place discovery | Overpass API (cached aggressively) |
| Context and lore | Wikipedia / Wikidata geosearch |

### Hosting

**Hetzner VPS 2** (existing server, `89.167.39.152`, Helsinki) — 2 vCPU AMD EPYC, 3.7 GB RAM, 75 GB SSD, 4 GB swap. Already runs a Paperclip AI orchestrator as the only other tenant; ports 80/443 are unused and available for Dispatch Zero. Sunk cost.

```
VPS 2 (Hetzner, Ubuntu 24.04)
├── (existing) Paperclip systemd service — internal only, firewalled
└── Dispatch Zero (Docker Compose project)
    ├── Caddy (reverse proxy, auto HTTPS via Let's Encrypt)
    ├── FastAPI backend
    ├── PostgreSQL + PostGIS (own instance, NOT shared with Paperclip)
    ├── Redis
    ├── Static frontend assets
    └── Kokoro TTS service
```

Resource budget for the Dispatch Zero stack: target ≤ 2 GB resident memory and ≤ 5 GB disk for v1. The 4 GB swap is a safety margin for Kokoro synthesis spikes, not a planning baseline. UFW is active and limited to 22, 80, 443 once Dispatch Zero is deployed.

### Authentication

**Callsign and password.** On signup, the user picks a unique (case-insensitive) callsign and a password. No email is collected. The callsign serves as both the login identifier and the in-product display name.

Sessions are kept in a signed `HttpOnly`, `Secure`, `SameSite=Lax` cookie containing the user UUID and an expiry, refreshed on activity (30-day idle window). Passwords are stored as argon2id hashes. Login is rate-limited per IP via Redis (5 attempts per 15 minutes). No CAPTCHA, no 2FA, no email verification, no OAuth in v1.

**No password reset.** A lost or forgotten credential is treated, in-fiction, as a compromised agent — the file is sealed and a new identity must be created. Zero delivers the rule at signup in style-appropriate phrasing (clipped and clinical in Agency, warm but firm in Pulp, ceremonial in Guild). This decision eliminates the need for any email infrastructure (no transactional email provider, no SMTP) and is consistent with the product's tone.

A future opt-in recovery mechanism (one-time recovery code shown at signup, saved by the user offline) may be added in Phase 2 if real users request it. Email-based password reset is not on the roadmap.

---

## Cost Profile

| Service | Cost |
|---|---|
| Hetzner VPS 2 | €0/month (sunk cost — existing server) |
| Ollama Cloud | ~$20/month |
| All other services | Free |
| **Total** | **~$20/month** |

---

## Data Model

### Place

| Field | Notes |
|---|---|
| `id` | Internal UUID |
| `osm_id` | OpenStreetMap object ID |
| `name` | Place name |
| `category` | Mural, sculpture, memorial, historic, viewpoint |
| `coordinates` | PostGIS point |
| `tags` | Raw normalized OSM metadata |
| `description` | Enriched description from Wikipedia/Wikidata |
| `quality_score` | Computed quest-worthiness |
| `location_thumbs_up` | Aggregate positive location ratings |
| `location_thumbs_down` | Aggregate negative location ratings |
| `status` | Active, flagged, suspended, retired |

### Mission

| Field | Notes |
|---|---|
| `id` | Internal UUID |
| `place_id` | Linked place |
| `adventure_style` | Pulp, agency, guild |
| `briefing_text` | Main mission copy |
| `clue` | Directional hint |
| `badge_framing` | Style-specific badge flavor |
| `mission_thumbs_up` | Positive mission ratings |
| `mission_thumbs_down` | Negative mission ratings |
| `implicit_completions` | Verified completions without explicit rating |
| `audio_url` | Cached Kokoro TTS file path |
| `ai_model` | Model used to generate this mission |
| `status` | Active, needs_regen, retired |

### Mission Stop

| Field | Notes |
|---|---|
| `id` | Internal UUID |
| `mission_id` | Parent mission |
| `place_id` | Linked place for this stop |
| `display_order` | Visual ordering only, not required route |
| `required` | Whether stop is required for completion |

### User

| Field | Notes |
|---|---|
| `id` | Internal UUID |
| `callsign` | Unique case-insensitive login identifier and display name |
| `password_hash` | Argon2id hash; no recovery, no email collected |
| `adventure_style` | Current selected style |
| `completed_place_ids` | Array used for no-repeat filtering (place re-enters pool 90 days after last completion) |
| `missions_this_week` | Count of missions completed in current calendar week |
| `missions_last_week` | Count from prior week for display purposes |

### Completion

| Field | Notes |
|---|---|
| `id` | Internal UUID |
| `user_id` | Linked user |
| `mission_id` | Linked mission |
| `place_id` | Linked place |
| `photo_url` | Thumbnail JPEG path (`/uploads/completions/{user_id}/{completion_id}.jpg`) |
| `capture_lat` | Latitude at photo capture |
| `capture_lng` | Longitude at photo capture |
| `capture_accuracy_m` | Device-reported GPS accuracy |
| `had_exif` | Whether the uploaded photo had any EXIF data |
| `exif_datetime_delta_seconds` | Seconds between EXIF DateTimeOriginal and upload time (null if missing) |
| `had_exif_gps` | Whether the uploaded photo carried GPS EXIF (logged then stripped) |
| `verified` | Whether GPS-radius and capture-freshness checks both passed |
| `location_rating` | Up, down, none |
| `mission_rating` | Up, down, none |
| `location_reason` | Gone, not_found, inaccessible, unsafe, null |
| `completed_at` | Timestamp |

---


## Photo Capture and Storage

### What Gets Stored

Full-resolution photos are never stored. On capture, the server immediately:

1. Resizes the image to a maximum of 600×600px
2. Strips all EXIF metadata (privacy requirement — no GPS, device, or timestamp data retained)
3. Encodes as JPEG at 70% quality
4. Saves to local disk at `/uploads/completions/{user_id}/{completion_id}.jpg`

The result is approximately 20–40KB per completion. At 10,000 completions, total photo storage is approximately 300–400MB — well within the VPS disk budget with no external object storage needed.

### Why Not Full Resolution

Full resolution photos serve no product purpose after verification. The GPS check is the verification primitive. The thumbnail is sufficient for mission history display and the mission card. Full resolution would fill disk, create privacy risk, and add infrastructure complexity for no user benefit.

### EXIF Stripping

EXIF is **read first** for the freshness check (DateTimeOriginal) and audit fields, then stripped before any write to disk. The client-side photo is never trusted to be clean — stripping is mandatory and server-side. This removes location metadata, device fingerprinting, and original-timestamp data from the stored thumbnail. The user's local copy on their camera roll retains EXIF (their phone, their data); only our server-side artifact is cleansed.

### Retention

Thumbnails are retained indefinitely as part of the user's mission history. If a user deletes their account, all associated thumbnails are deleted. No other retention policy is needed at v1 scale.

---

## Mission Card (Social Sharing)

### What It Is

The mission card is a generated image produced at mission completion. It is the shareable artifact the user can save to their camera roll and post anywhere.

### Contents

- Completion thumbnail (the place the user photographed)
- Location name
- Mission code
- Zero's debrief sign-off line (one line, in character, per adventure style)
- User's callsign or display name
- Subtle adventure style identifier (small icon or accent color)
- Dispatch Zero wordmark

### Format

| Property | Value |
|---|---|
| Aspect ratio | 4:5 (portrait, Instagram-friendly) |
| Format | JPEG |
| Generation | Server-side at debrief completion |
| Aesthetic | Dossier visual language — dark chrome, monospace metadata, amber accent, thumbnail framed as a field photograph with thin rule border |

The card should look like a stamped mission file, not a social media graphic. The visual language must match the app.

### Social Sharing Strategy

- **Bluesky:** Deep link with pre-filled text
- **Mastodon:** Deep link with pre-filled text
- **Everywhere else:** User saves the mission card image to camera roll and posts manually

No other platform integrations. This is a conscious decision, not a placeholder for future work.

---

## Progression System Updates

### Weekly Missions Replace Daily Streak

Daily streaks create pressure that conflicts with the low-friction adventure promise. The progression system uses **weekly mission count** instead.

- "3 missions this week" is encouraging without being coercive
- No daily cliff, no grace day mechanic needed
- Fits the product's tone of optional discovery rather than compulsive daily engagement

Weekly count resets on Monday. Display shows current week count and last week count for context.

### Place Pool Re-entry

Places re-enter a user's eligible pool **90 days after their last completion** of that place. This is tracked via `last_completed_at` on the UserPlaceHistory record rather than a permanent exclusion boolean.

This prevents small-town users from exhausting their local pool permanently within weeks of joining.

### Auto-Retire Threshold

A place is automatically flagged for review when it receives **3 or more negative location ratings in its last 5 location ratings**. Flagged places are removed from the active pool pending manual review. They are not permanently deleted — a review can restore them to active status.

---

## Open Questions

### Still Undecided

- **Final production domain** — `null.quest`, `cipher.quest`, `echo.quest`, or other. Not needed until launch.
- **Exact Kokoro voice assignments** — which of the 54 preset voices maps to each handler style.
- **Handler avatar final art direction** — to be created with Mistral Medium / Flux credits.
- **Disk growth headroom on VPS 2** — 18 GB free after swap. Sufficient for v1 launch but will need monitoring; migration path to a larger Hetzner box exists if traffic justifies.

### Fully Decided

- Product name: Dispatch Zero
- Working URL: dispatchzero.ataary.com
- Handler name: Zero (single unified character — no separate persona names; tone and voice vary per style)
- Handler mystery: preserved, no biography, obscured avatars
- Python + FastAPI
- PostgreSQL + PostGIS
- Callsign + password authentication (argon2id hashing, signed-cookie sessions, 30-day idle expiry, Redis-backed login rate limit)
- No email collected, no password reset — lost credentials are framed in-fiction as a compromised agent
- No transactional email provider, no SMTP, no mail server involvement of any kind
- Hetzner VPS 2 hosting (`89.167.39.152`, 2 vCPU / 3.7 GB RAM / 75 GB disk / 4 GB swap; coexists with Paperclip orchestrator on same box, no shared services)
- Leaflet + CartoDB map stack
- Kokoro-82M TTS self-hosted on VPS
- Ollama Cloud for AI mission generation (~$20/mo); fallback is local Ollama with smaller model
- In-app photo capture with geolocation-based verification
- No photo override button
- Thumbnail-only photo storage (600×600px max, EXIF stripped, 70% JPEG, ~20–40KB each)
- Full resolution photos never stored
- Mission card generated at completion (4:5 JPEG, dossier aesthetic, includes thumbnail)
- Bluesky and Mastodon deep links + save-to-camera-roll mission card
- No other social platform integrations — conscious decision
- Scout / Recon / Expedition mission tiers (Scout only for v1)
- User-controlled stop order for multi-stop missions
- Two-axis rating system (location + mission independently)
- Mission library with reuse logic
- Places re-enter user pool after 90 days (not permanent exclusion)
- Auto-retire threshold: 3 negative location ratings in last 5 → flagged for review
- Weekly mission count replaces daily streak
- Vision-based debrief enrichment pushed to Phase 3
- Public Nominatim with aggressive Redis cache (geocoding TTL 30 days, Overpass TTL 7 days)
- Redis cache TTL strategy defined
- Self-hosted Nominatim/Overpass deferred to Phase 2 if traffic justifies

---

## MVP Scope

The MVP validates the core loop only:

- Callsign + password account creation
- Adventure style selection (all three)
- ZIP code or geolocation input
- Scout missions only
- Real place discovery from approved categories
- AI-generated mission briefing via Ollama Cloud
- Optional TTS playback via Kokoro
- In-app camera capture
- Geolocation-based verification
- Completion count + weekly activity counter, first badge set
- Two-axis location and mission ratings
- Mission library save and reuse
- No-repeat place filtering
- Optional map reveal (Leaflet + CartoDB)
- Bluesky and Mastodon share links

---

## Roadmap

### Phase 1 — MVP

- Build the single-stop Scout mission loop end to end.
- Launch all three adventure styles with Zero personas.
- Ship handler avatars and Kokoro voices.
- Implement mission library and rating logic.
- Verify proof via capture geolocation.

### Phase 2 — Expansion

- Add Recon missions (two stops, user-chosen order).
- Richer badge system and progression polish.
- Personal completed-mission map.
- Stronger Wikipedia/Wikidata enrichment in debrief.
- Full Bluesky AT Protocol posting.
- Optional vision-based debrief enrichment (Phase 3 only — removed from Phase 2).

### Phase 3 — Depth

- Add Expedition missions (three or more stops).
- Consider native mobile app if web traction justifies it.
- Migrate to dedicated `.quest` domain.
- Advanced social and community features.
- Self-hosted tile stack if CartoDB changes.

---

*Document updated April 2026. All decisions current as of this date.*
