# Phase 7: Mission UI Screens — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The full mission lifecycle is operable on a phone. A real user can tap "Request Dispatch" on Home, see a Dispatch summary, read the Full Brief, accept the mission, walk to the place with a live compass + distance readout, capture proof via the OS camera, see verification + debrief, and rate the location and mission. End of Phase 7 = the app is genuinely usable in the field.

**Architecture:** Eight new screens stacked on top of the Phase 5 API and the Phase 6 frontend foundation. URL-keyed by mission id (`/mission/:id/dispatch`, `/mission/:id/brief`, etc.) so the back button and reload work mid-flow. A small in-memory `flow.js` store caches the in-flight mission + last-known GPS so subsequent screens don't re-fetch. Each screen lives in its own module under `frontend/static/js/screens/mission/`.

**Backend additions:** one new endpoint (`GET /missions/{id}`) and a small extension to `MissionOut` to include the nested `place` (name, category, lat, lng). Without this, the Transit screen has no way to compute distance to the target.

**Decision defaults (override before starting):**

| Decision | Default | Why |
|---|---|---|
| Routing pattern | `/mission/:id/{dispatch,brief,objective,transit,capture,debrief}` + `/completions/:id/rate` | URL-keyed survives reload + back button. Each screen knows what mission it's working on. |
| Mission data flow | Phase 5's `POST /missions/request` returns the mission. Each screen calls `GET /missions/{id}` on mount (with `flow.js` cache to avoid redundant calls) | Single source of truth on the server. Cache hides the latency. |
| Place coordinates | Returned in `MissionOut.place` (NEW nested object: name, category, lat, lng) | Transit needs lat/lng to compute distance + bearing. |
| GPS strategy | `navigator.geolocation.watchPosition({ enableHighAccuracy: true })` from Objective onward; fresh `getCurrentPosition` at capture if cache > 5s old | Watch keeps distance live during transit; capture uses freshest fix. |
| Compass strategy | `DeviceOrientationEvent` with iOS permission prompt on first Transit visit. Falls back to text-only bearing if denied or unsupported. | True compass adds delight; not blocking. |
| Capture method | `<input type="file" accept="image/*" capture="environment">` styled as a big tappable area | Locked spec decision — auto-saves to camera roll on iOS as a side effect. |
| Verification screen | Brief auto-advancing holding state (~1-2s) while the multipart POST is in-flight | Hides the latency from the user; debriefs immediately on response. |
| Within-radius detection | Hard-coded `RADIUS_M = 80` in JS, mirroring server `gps_verification_radius_m` | One value per place spec change requires touching both. Acceptable for v1. |
| Capture button activation | Enabled when distance ≤ RADIUS_M; otherwise shows "Closer, agent — Xm to target" | Spec aligned: don't let users waste a capture from across town. |
| Failure UX (out of radius / stale EXIF) | API 422 returns generic in-character message; client shows it as a fault block, doesn't differentiate | Per spec: user must not learn whether GPS or EXIF failed. |
| Rating optional? | Yes — "Skip" returns to Home | Per spec: rating is "implicit positive" without explicit input. |
| Mission card on Debrief | NOT in Phase 7 — Phase 9 ships it | Keep Phase 7 focused. |
| Map view button on Transit | NOT in Phase 7 — Phase 8 wires it | Same. |
| Audio playback on Brief | NOT in Phase 7 — Phase 11 wires it | Same. |

**Repo layout deltas:**

```
dispatch-zero/
├── src/dispatchzero/
│   ├── missions/routes.py                # MODIFIED — add GET /missions/{id}; extend MissionOut response (place nested)
│   └── schemas/missions.py               # MODIFIED — add PlaceMini + MissionOut.place
├── frontend/
│   └── static/
│       ├── js/
│       │   ├── flow.js                   # NEW — in-flight mission cache + GPS watch helper
│       │   └── screens/mission/
│       │       ├── dispatch.js
│       │       ├── brief.js
│       │       ├── objective.js
│       │       ├── transit.js
│       │       ├── capture.js
│       │       ├── verification.js       # actually a tiny in-Capture state, but extracted for clarity
│       │       ├── debrief.js
│       │       └── rate.js
│       └── css/screens.css               # MODIFIED — compass, capture, big-distance readouts
└── tests/
    └── test_missions_routes.py           # MODIFIED — add GET /missions/{id} test
```

---

### Task 1: Backend — extend MissionOut with nested place + add GET /missions/{id}

**Files:**
- Modify: `src/dispatchzero/schemas/missions.py`
- Modify: `src/dispatchzero/missions/routes.py`
- Modify: `tests/test_missions_routes.py`

**Schema change:** add a small `PlaceMini` model and nest it into `MissionOut`:

```python
class PlaceMini(BaseModel):
    id: uuid.UUID
    name: str | None
    category: str
    lat: float
    lng: float


class MissionOut(BaseModel):
    id: uuid.UUID
    place_id: uuid.UUID
    place: PlaceMini  # NEW — nested
    adventure_style: str
    dispatch_summary: str
    briefing_text: str
    clue: str | None
    badge_framing: str | None
    audio_url: str | None
    ai_model: str | None
    status: str
```

**Route change:** add a helper `mission_to_out(mission, place)` that builds MissionOut with the nested place. Use it in `generate`, `request_mission`, AND the new `GET /missions/{id}`. The helper needs the Place row, so callers fetch it once.

For `GET /missions/{id}`:

```python
@router.get("/{mission_id}", response_model=MissionOut)
async def get_mission(
    mission_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> MissionOut:
    mission = (await db.execute(select(Mission).where(Mission.id == mission_id))).scalar_one_or_none()
    if mission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    place = (await db.execute(select(Place).where(Place.id == mission.place_id))).scalar_one()
    return await _mission_to_out(db, mission, place)
```

`_mission_to_out` is async because reading lat/lng from PostGIS Geography needs `ST_X/ST_Y`. Reuse the `_place_lat_lng` helper from `services/mission_flow.py` (move it to `services/place_geo.py` so it's importable without circular dep, OR just duplicate the 4-line query).

**Tests to add in `test_missions_routes.py`:**
- `test_get_mission_returns_full_payload_with_nested_place` — POST signup, generate a mission, GET /missions/{id}, assert response includes place.lat, place.lng, place.name, place.category
- `test_get_mission_404_for_unknown_id` — GET random UUID, expect 404
- `test_get_mission_requires_auth` — clear cookies, expect 401

Update existing tests that destructure MissionOut to expect the new `place` field (most don't check it, but the smoke test in test_missions_flow_routes.py asserts `body["adventure_style"]` etc. — those still work since they don't assert on missing fields).

```bash
./deploy/test.sh   # all tests still pass + 3 new
git add ...
git commit -m "feat: GET /missions/{id} + nested place coords in MissionOut"
```

---

### Task 2: Frontend — `flow.js` (in-flight mission cache + geolocation helper)

**File:** `frontend/static/js/flow.js`

A tiny module managing in-flight state. NOT a full state machine — just a cache + helpers:

```javascript
import { api } from "./api.js";

let _cached = null;             // { id, mission_data, fetched_at }
let _watchId = null;            // navigator.geolocation watch handle
let _lastFix = null;            // { lat, lng, accuracy_m, ts }
const _fixListeners = new Set();

export async function loadMission(id) {
  if (_cached?.id === id && (Date.now() - _cached.fetched_at) < 60000) {
    return _cached.mission_data;
  }
  const r = await api.get(`/missions/${id}`);
  if (!r.ok) throw new Error(r.data?.detail || "Mission not found");
  _cached = { id, mission_data: r.data, fetched_at: Date.now() };
  return r.data;
}

export function clearMissionCache() { _cached = null; }

export function startWatchingPosition() {
  if (_watchId !== null) return;
  if (!navigator.geolocation) return;
  _watchId = navigator.geolocation.watchPosition(
    (pos) => {
      _lastFix = {
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy_m: pos.coords.accuracy,
        ts: Date.now(),
      };
      for (const fn of _fixListeners) fn(_lastFix);
    },
    () => { /* ignore — UI shows "no fix yet" */ },
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 30000 }
  );
}

export function stopWatchingPosition() {
  if (_watchId !== null) {
    navigator.geolocation.clearWatch(_watchId);
    _watchId = null;
  }
}

export function getLastFix() { return _lastFix; }
export function onFix(fn) {
  _fixListeners.add(fn);
  return () => _fixListeners.delete(fn);
}

export async function getFreshFix({ maxAgeMs = 5000 } = {}) {
  if (_lastFix && (Date.now() - _lastFix.ts) < maxAgeMs) return _lastFix;
  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const fix = {
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy_m: pos.coords.accuracy,
          ts: Date.now(),
        };
        _lastFix = fix;
        resolve(fix);
      },
      (err) => reject(err),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
    );
  });
}

// Pure math helpers — Haversine + bearing
const R_EARTH_M = 6_371_000;

export function distanceM(lat1, lng1, lat2, lng2) {
  const phi1 = lat1 * Math.PI / 180;
  const phi2 = lat2 * Math.PI / 180;
  const dPhi = (lat2 - lat1) * Math.PI / 180;
  const dLam = (lng2 - lng1) * Math.PI / 180;
  const a = Math.sin(dPhi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLam / 2) ** 2;
  return 2 * R_EARTH_M * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export function bearingDeg(lat1, lng1, lat2, lng2) {
  const phi1 = lat1 * Math.PI / 180;
  const phi2 = lat2 * Math.PI / 180;
  const dLam = (lng2 - lng1) * Math.PI / 180;
  const y = Math.sin(dLam) * Math.cos(phi2);
  const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLam);
  return ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
}
```

Commit standalone — no test for it; will be exercised by the screens.

---

### Task 3: Wire "Request Dispatch" on Home → Dispatch screen

**Files:**
- Modify: `frontend/static/js/screens/home.js`
- Modify: `frontend/static/js/app.js`
- Create: `frontend/static/js/screens/mission/dispatch.js`

**Home change:** the Request Dispatch button is currently disabled. Enable it. On click:
1. Get current GPS via `getFreshFix()`. If user denies / no fix, show error.
2. POST `/missions/request` with `{lat, lng, radius_m: 2000}`.
3. On success: cache mission via `flow.loadMission` (well, just stash the response data) and `navigate(`/mission/${mission.id}/dispatch`)`.
4. On 404 (no places nearby): show "No eligible targets within 2 km, agent."
5. On 503 (Ollama down): show "Dispatch line is unreliable — try again."

Display a transient loading state while the request is in flight ("Acquiring target…").

**Dispatch screen** (`frontend/static/js/screens/mission/dispatch.js`):

```
Header:  // dispatch zero //          [mission code = first 8 chars of id]
Content:
  Small handler-mark row (Zero avatar 24px + "ZERO // <STYLE>")
  Subtitle: "DISPATCH"
  Title: place.name (e.g. "Garbage Goat")
  Mono caption: place.category (e.g. "sculpture")
  Big serif/body block: dispatch_summary (the 2-3 line preview)
Actions:
  Secondary: "Open Brief" → /mission/:id/brief
  Primary:   "Accept" → /mission/:id/objective
```

Implement via `el()` builder. Fetch mission via `flow.loadMission(id)`.

**Route registration in `app.js`:**
```javascript
import { dispatch as missionDispatch } from "./screens/mission/dispatch.js";
defineRoute("/mission/", () => missionDispatch());  // won't work — need param routing
```

**Router enhancement needed.** The current router is exact-match. Add wildcard support: `defineRoute("/mission/:id/dispatch", (params) => missionDispatch(params.id))`. Implement with a simple `RouteEntry { pattern: RegExp, paramNames: [], render: fn }`. ~15 LOC addition.

```bash
git add ... && git commit -m "feat: param-aware client router + Request Dispatch wiring + Dispatch screen"
```

---

### Task 4: Full Brief screen

**File:** `frontend/static/js/screens/mission/brief.js`

```
Header:  // dispatch zero //          [mission code]
Content (scrollable — only screen that allows scroll):
  Subtitle: "FULL BRIEF"
  Title: place.name
  Subtle metadata row: category | (description if present, in muted)
  Body: briefing_text rendered as serif paragraphs (split on \n\n)
  Optional: clue rendered in monospace + accent at the bottom, with a "FIELD HINT" subtitle
Actions:
  Primary: "Acknowledged" → back to /mission/:id/dispatch
```

Important: this screen is the documented exception to the no-scroll rule. Apply `.content.scrollable`.

```bash
git add ... && git commit -m "feat: Full Brief screen (only screen that allows scroll)"
```

---

### Task 5: Objective + Transit screens (compass + watch)

**Files:**
- Create: `frontend/static/js/screens/mission/objective.js`
- Create: `frontend/static/js/screens/mission/transit.js`
- Modify: `frontend/static/css/screens.css` (compass arrow + big distance)

**Objective screen:**

```
Header:  // dispatch zero //   [mission code]
Content:
  Subtitle: "OBJECTIVE"
  Title: place.name
  Mono row: category
  Description (if present, muted)
  Distance readout (mono, large): "Acquiring fix…" then "Xm" once fix arrives
Actions:
  Primary: "Begin Transit" → /mission/:id/transit
```

On render: `flow.startWatchingPosition()`. `flow.onFix(fix => updateDistance(fix))`. Calculate distance via `distanceM()`.

**Transit screen** is the operational center:

```
Header:  // dispatch zero //   [mission code]
Content:
  [Compass SVG arrow — 200x200, centered] — points toward target
  Big mono distance: "47 m" (live)
  Muted: "BEARING N42E" (live)
  Subtle: place.name, category
Actions:
  Primary: "Capture" — DISABLED until distance ≤ 80m, then ENABLED, then on tap → /mission/:id/capture
  Secondary muted: "Stand down" (cancel back to Home)
```

**Compass behavior:**
- On mount, check `typeof DeviceOrientationEvent.requestPermission === "function"` (iOS).
  - If yes: render a "Enable compass" overlay on the arrow. Tap it → call `requestPermission()`, on grant → start `deviceorientation` listener.
  - If no (Android): just `addEventListener("deviceorientation", handler)`.
- `handler(event)`:
  - iOS: use `event.webkitCompassHeading` (true heading, 0=N, 90=E)
  - Android: use `360 - event.alpha` (alpha is counter-clockwise from N — invert)
- `arrowRotation = (bearingToTarget - deviceHeading + 360) % 360`
- Apply via `transform: rotate(Xdeg)` on the SVG arrow

Fall back to a static arrow that just shows bearing-as-text if orientation unavailable/denied.

**CSS (in `screens.css`)**:

```css
.compass {
  width: 200px;
  height: 200px;
  margin: 0 auto;
  border: 1px solid var(--surface-rule);
  border-radius: 50%;
  position: relative;
  display: grid;
  place-items: center;
}
.compass-arrow {
  width: 80%;
  height: 80%;
  transition: transform 200ms ease-out;
}
.distance-readout {
  font-family: var(--font-mono);
  font-size: var(--t-3xl);
  color: var(--accent);
  text-align: center;
  letter-spacing: 0.05em;
}
.bearing-readout {
  font-family: var(--font-mono);
  font-size: var(--t-xs);
  text-transform: uppercase;
  color: var(--text-muted);
  letter-spacing: 0.12em;
  text-align: center;
}
```

Compass arrow as inline SVG:
```html
<svg class="compass-arrow" viewBox="0 0 100 100">
  <path d="M50 10 L60 70 L50 60 L40 70 Z" fill="var(--accent)"/>
</svg>
```

On unmount (route change away): `flow.stopWatchingPosition()` and `removeEventListener("deviceorientation")`. Each screen should return a cleanup function or use a MutationObserver — simplest is to register cleanup on the screen element via `el.addEventListener("DOMNodeRemoved", ...)` or just listen for the next route change.

Cleanest: extend the router to optionally accept a `{ render, cleanup }` object. When swapping screens, call previous `cleanup()` first. Add this in Task 5 since it's needed here.

```bash
git add ... && git commit -m "feat: Objective + Transit screens with live compass and distance"
```

---

### Task 6: Capture screen + the embedded Verification holding state

**File:** `frontend/static/js/screens/mission/capture.js`

```
Header:  // dispatch zero //   [mission code]
Content:
  Subtitle: "CAPTURE"
  Title: place.name
  Big tappable area:
    label wrapping <input type="file" accept="image/*" capture="environment">
    Inside the label: a 100x100 SVG (camera icon or aperture), text "TAP TO CAPTURE"
  Muted footnote: "Your photo saves to your camera roll automatically."
Actions:
  Secondary muted: "Cancel" → back to /mission/:id/transit
```

When user taps and selects (or shoots) a photo, `<input>` fires `change` event with the file in `e.target.files[0]`.

**Capture handler:**
1. Hide the input UI; show "TRANSMITTING PROOF" full-screen state (the embedded "Verification" screen — no separate route).
2. `getFreshFix({ maxAgeMs: 10000 })` to get current GPS.
3. Build FormData with photo + lat + lng + accuracy_m.
4. `api.postForm(`/missions/${id}/capture`, fd)`.
5. On 200: cache the debrief response, `navigate(`/mission/${id}/debrief`)` and pass debrief via `flow.setLastDebrief(debrief)` (small addition to flow.js).
6. On 422 (verification failed): show in-character fault block "The proof is not yet sufficient, agent. Try again." Re-show the capture UI. Give them a chance to re-shoot.
7. On other error: same fault block with generic "Transmission failed."

The "Verification" screen from the spec is just a transient inline state, not its own route. Cleaner UX, fewer histories to manage.

**CSS:**
```css
.capture-target {
  display: grid;
  place-items: center;
  gap: var(--s-3);
  padding: var(--s-6);
  border: 2px dashed var(--accent);
  border-radius: var(--r-md);
  cursor: pointer;
  min-height: 200px;
}
.capture-target input[type="file"] { display: none; }
.capture-target.transmitting {
  border-style: solid;
  pointer-events: none;
}
```

```bash
git add ... && git commit -m "feat: Capture screen (native camera intent + multipart upload + inline transmitting state)"
```

---

### Task 7: Debrief screen

**File:** `frontend/static/js/screens/mission/debrief.js`

```
Header:  // dispatch zero //   [completion code = first 8 chars]
Content:
  Subtitle: "DEBRIEF"
  Title: "Acknowledged."
  Body: dispatch_summary again (or a fresh debrief blurb? — for v1, use dispatch_summary; Phase 4's prompt could later add a debrief field)
  Stats row:
    "Completions" — big mono number = user_completions_count from debrief response
    "This week" — mono = user_missions_this_week
  Optional badge_framing if mission included one — small accented chip
Actions:
  Primary: "Rate Mission" → /completions/:id/rate
  Secondary: "Skip — Return to Base" → / (Home)
```

If user lands here with no cached debrief (e.g. opened the URL fresh), fetch via `GET /missions/{id}` for the dispatch_summary as a fallback, but the stats won't be available. Show graceful degradation.

```bash
git add ... && git commit -m "feat: Debrief screen with completion stats + rating CTA"
```

---

### Task 8: Rating screen

**File:** `frontend/static/js/screens/mission/rate.js`

```
Header:  // dispatch zero //   [completion code]
Content:
  Subtitle: "RATE"
  Two two-button rows:
    "THIS PLACE"   [👎] [👍]
    "THIS MISSION" [👎] [👍]
  When location 👎 selected, reveal a select:
    "Reason: gone | not_found | inaccessible | unsafe"
Actions:
  Primary: "Submit" → POST /missions/completions/:id/rate → /
  Secondary muted: "Skip" → /
```

State held locally in the screen (no need for flow.js). On submit, POST the JSON; on success, navigate to Home (which will re-fetch /auth/me and show the updated counts).

Use Unicode thumbs (👎👍) or simple SVG icons. For dossier consistency, use small monospace symbols `[+]` `[-]` instead — matches the visual register better. Final call: small SVG arrows `▲` and `▼` rendered as buttons with accent on selected state.

```css
.thumb {
  width: 64px; height: 48px;
  display: grid; place-items: center;
  font-family: var(--font-mono);
  font-size: var(--t-xl);
}
.thumb.selected {
  background: var(--accent);
  color: var(--surface-bg);
  border-color: var(--accent);
}
```

```bash
git add ... && git commit -m "feat: Rating screen with two-axis thumbs and optional reason"
```

---

### Task 9: Real-device test checklist

Not a code task — Trevor walks through the loop on a real phone before declaring Phase 7 done.

**Checklist:**

**iOS Safari (iPhone):**
- [ ] Sign up fresh with a `phase7_*` callsign
- [ ] Tap "Request Dispatch" — browser prompts for location permission, allow
- [ ] Land on Dispatch with a real Spokane place
- [ ] "Open Brief" → scrollable Full Brief, "Acknowledged" returns
- [ ] "Accept" → Objective with correct distance to target
- [ ] "Begin Transit" → Transit
- [ ] On first Transit visit: tap "Enable compass", grant motion permission
- [ ] Walk a few meters — distance counter updates, compass arrow rotates
- [ ] Walk into the 80m radius — Capture button enables
- [ ] "Capture" → camera opens (NOT the photo picker)
- [ ] Take a photo
- [ ] Returns to app, "TRANSMITTING" briefly, then Debrief
- [ ] Debrief shows updated completions count
- [ ] Photo IS in Camera Roll (verify in Photos app)
- [ ] "Rate Mission" → submit a thumbs-up on both axes → Home
- [ ] Home shows incremented completions count

**Android Chrome:**
- [ ] Repeat the same loop. On Transit, no permission prompt for compass — should just work.

**Failure modes (intentional):**
- [ ] Try Capture from outside 80m: button is disabled with "Closer, agent — Xm to target"
- [ ] Network drop during Capture POST: in-character "Transmission failed" message; can retry
- [ ] Reload the page mid-Transit: should resume on `/mission/:id/transit` and re-fetch mission data

If any check fails: surface it before declaring Phase 7 done.

---

### Task 10: Deploy + cleanup test users + health check

```bash
./deploy/deploy.sh
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d dispatchzero -c \"DELETE FROM completions WHERE user_id IN (SELECT id FROM users WHERE callsign_lower LIKE 'phase7%'); DELETE FROM users WHERE callsign_lower LIKE 'phase7%';\""
ssh root@89.167.39.152 "find /opt/dispatchzero/uploads/completions/ -mindepth 1 -maxdepth 1 -type d -mtime -1 -print"  # spot-check then rm if needed
ssh root@89.167.39.152 "systemctl is-active paperclip.service && free -h | head -2 && df -h /"
```

---

## Phase 7 — Definition of Done

- All backend tests pass (existing 135 + 3 new mission-get tests = 138).
- Trevor walks to a real Spokane place (the Garbage Goat is the canonical target), opens the PWA on his phone, completes the entire flow without dev tools, and sees his completion count tick up by 1.
- Photo lands in the user's Camera Roll automatically.
- Compass arrow rotates correctly toward the target as Trevor turns.
- Capture button is correctly gated by the 80m radius.
- Verification failure (e.g. force a stale photo from gallery) returns the in-character message; doesn't crash.
- Page reload mid-flow resumes correctly from URL.
- Paperclip restart count unchanged.

---

## Critical Files To Be Created In Phase 7

| File | Purpose |
|---|---|
| `frontend/static/js/flow.js` | In-flight mission cache + watchPosition + Haversine/bearing helpers |
| `frontend/static/js/screens/mission/dispatch.js` | Dispatch summary preview |
| `frontend/static/js/screens/mission/brief.js` | Full briefing (only scrollable screen) |
| `frontend/static/js/screens/mission/objective.js` | Destination preview + initial distance |
| `frontend/static/js/screens/mission/transit.js` | Live compass + distance + capture-gate |
| `frontend/static/js/screens/mission/capture.js` | Camera intent + multipart upload + inline transmitting state |
| `frontend/static/js/screens/mission/debrief.js` | Server response + updated stats |
| `frontend/static/js/screens/mission/rate.js` | Two-axis ratings + optional reason |
| `frontend/static/js/router.js` (modified) | Param-aware route patterns + cleanup hook |
| `frontend/static/js/screens/home.js` (modified) | Wire "Request Dispatch" to start the flow |
| `frontend/static/css/screens.css` (modified) | Compass, distance readout, capture target, thumb buttons |
| `src/dispatchzero/missions/routes.py` (modified) | + GET /missions/{id} |
| `src/dispatchzero/schemas/missions.py` (modified) | + PlaceMini, MissionOut.place |

---

## Open Decisions

| Decision | Default | Where to change |
|---|---|---|
| Capture-gate radius | 80m (hard-coded in JS, mirrors server) | `frontend/static/js/screens/mission/transit.js` |
| Mission cache TTL | 60s | `flow.js` `loadMission` |
| GPS watch options | `enableHighAccuracy: true, maximumAge: 5s, timeout: 30s` | `flow.js` `startWatchingPosition` |
| Compass behavior on iOS perm denial | Falls back to text-only bearing | `transit.js` |
| Rating "Skip" | Returns to Home, no API call | `rate.js` |
| Inline Verification state | Yes — no separate route | `capture.js` |
| Photo retry on 422 | Yes — re-show capture UI | `capture.js` |
| Mission card / map / audio in Phase 7 | NO — those are Phases 9 / 8 / 11 | Defer |

---

## What Comes Next

**Phase 8 — Map view.** Optional Leaflet+CartoDB tile-rendered map toggleable from Transit. Two markers (user, destination), per-style tile theme, no other controls. Quick to ship after Phase 7 since the data plumbing is already there.
