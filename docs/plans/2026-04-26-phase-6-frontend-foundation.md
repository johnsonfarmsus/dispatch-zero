# Phase 6: Frontend Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A PWA shell at `https://dispatchzero.ataary.com` that real users can install on a phone, sign up, log in, pick (or change) an adventure style, and land on a Home screen showing their callsign + style + completions count + missions-this-week. Phase 7 plugs the mission flow screens into this shell.

**Architecture:** Single-page application served as static files by FastAPI's `StaticFiles`. **Vanilla JavaScript modules** — no framework, no build step. One `index.html` + a small client-side router + per-screen modules. Auth flows through HttpOnly session cookies — no token storage in JS. CSS variables drive per-style theming (`<body data-style="...">`).

**Why no framework / no HTMX / no Alpine:**

- HTMX shines for "server-renders HTML chunks, client swaps them in" but breaks down for live device interaction (compass, geolocation watch, camera capture coming in Phase 7).
- React/Preact/Svelte all need a build step. The whole app is ~9 screens with one to two interactive elements each. We don't need component diffing.
- Vanilla JS modules + the platform APIs cover everything. No bundle, no toolchain.

**Code style: DOM construction via a tiny `el()` helper, not `innerHTML`.** All screens build their structure via small composable factory functions. This avoids any XSS risk from interpolated values and reads cleanly.

**What ships in Phase 6:**

| Screen | Purpose |
|---|---|
| Splash | Brief "verifying credentials" landing during initial /auth/me check |
| Signup | Callsign + password + style → POST /auth/signup → Home |
| Login | Callsign + password → POST /auth/login → Home |
| Home | Callsign, current style + avatar, completions count, missions this week |
| Style picker | Switch pulp/agency/guild post-signup |

What does NOT ship: the mission flow screens (Phase 7), maps (Phase 8), mission cards (Phase 9), social sharing (Phase 10), TTS (Phase 11), badges (Phase 12).

**Decision defaults (override before starting):**

| Decision | Default | Why |
|---|---|---|
| Stack | Vanilla JS modules + CSS variables, no build step | Fits dossier minimalism; suits the live-device screens coming in Phase 7 |
| DOM construction | `el(tag, attrs, ...children)` helper everywhere; no `innerHTML` | Safe by construction; readable |
| Routing | Custom 50-LOC client router (`history.pushState`, hash-free) | One dependency-free file |
| Style application | `<body data-style="agency">` + CSS variable swap | Single source of truth |
| Auth state | Cookie + `GET /auth/me` on app load | No JS token mgmt |
| Static serving | FastAPI `StaticFiles` mounted at `/static/`; SPA fallback returns `index.html` | Simplest possible |
| PWA icon | Reuses `zero-agency.png` as default install icon | Trevor can make a dedicated logo in Phase 12 |
| Service worker | Cache the shell, network-first for `/auth`, `/places`, `/missions`, `/healthz` | "Offline-first" is a Phase 14 concern |
| Frontend test strategy | Server-side tests verify static files are served + content types. No JS unit tests in v1. Manual phone testing is the truth. | Most failure modes are visual/device-specific |
| Browser target | Modern Safari (iOS 17+) and Chrome (Android 14+). No transpilation. | Mobile-first PWA |
| Avatar paths | Move 3 PNGs from project root → `frontend/static/avatars/zero-{pulp,agency,guild}.png` | Filenames match in-product identity |

**Repo layout deltas:**

```
dispatch-zero/
├── frontend/
│   ├── index.html
│   ├── manifest.webmanifest
│   ├── service-worker.js
│   ├── favicon.svg
│   └── static/
│       ├── css/{tokens,layout,screens}.css
│       ├── js/
│       │   ├── app.js          # bootstrap + route registration
│       │   ├── router.js       # 50-LOC client router
│       │   ├── api.js          # fetch wrapper, 401 handling
│       │   ├── state.js        # in-memory user store
│       │   ├── dom.js          # el() helper + escape utilities
│       │   └── screens/{splash,signup,login,home,style-picker}.js
│       └── avatars/zero-{pulp,agency,guild}.png
├── src/dispatchzero/main.py    # MODIFIED — StaticFiles mount + SPA fallback
├── src/dispatchzero/auth/routes.py  # MODIFIED — adds POST /auth/style
└── tests/test_frontend_serving.py   # NEW
```

---

### Task 1: Move/rename avatars

```bash
mkdir -p frontend/static/avatars frontend/static/css frontend/static/js/screens
git mv director-zero.png   frontend/static/avatars/zero-agency.png
git mv professor-zero.png  frontend/static/avatars/zero-pulp.png
git mv guildmaster-zero.png frontend/static/avatars/zero-guild.png
# Optional: keep the older red guild as alt
[ -f guildmaster-zero-red.png ] && git mv guildmaster-zero-red.png frontend/static/avatars/zero-guild-alt-red.png
git commit -m "chore: move zero avatars into frontend/static/avatars"
```

---

### Task 2: Mount StaticFiles + SPA fallback in FastAPI (TDD)

**Write `tests/test_frontend_serving.py`** with seven tests:
1. `GET /` returns 200 with `<!doctype html>` + "Dispatch Zero" in the body
2. `GET /signup` (any non-API route) also returns the index HTML (SPA fallback)
3. `GET /healthz` still returns `{"status":"ok"}`
4. `GET /auth/me` still returns 401 (API not swallowed by SPA fallback)
5. `GET /manifest.webmanifest` returns 200 with manifest/json content-type
6. `GET /service-worker.js` returns 200 with `javascript` content-type
7. `GET /static/avatars/zero-agency.png` returns 200 with image content-type, body > 1KB

**Replace `src/dispatchzero/main.py`** to:
- Keep all existing routers (`auth`, `places`, `missions`) declared FIRST so they win.
- Keep `/healthz`.
- `app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR / "static"), check_dir=False))`.
- Top-level routes for `/manifest.webmanifest`, `/service-worker.js`, `/favicon.svg` returning the right files with correct media types.
- Final catchall `@app.get("/{full_path:path}")` returns `FileResponse(_INDEX_HTML)`.

**Create stub frontend files** so the tests pass:
- `frontend/index.html` — minimal HTML with `<div id="app"></div>` and `<script type="module" src="/static/js/app.js"></script>`. Body has `data-style="agency"`.
- `frontend/manifest.webmanifest` — name "Dispatch Zero", display "standalone", background and theme `#0e0c0a`, single 512×512 icon at `/static/avatars/zero-agency.png`.
- `frontend/service-worker.js` — install handler caches the shell list, activate handler clears old caches, fetch handler is network-first for `/auth`, `/places`, `/missions`, `/healthz` (let it pass through), cache-first for everything else.
- `frontend/favicon.svg` — tiny SVG with a "0" glyph in cyan on charcoal.
- Empty stubs for `frontend/static/js/{app,router,api,state,dom}.js` and `frontend/static/css/{tokens,layout,screens}.css` so the SW pre-cache doesn't 404.

```bash
./deploy/test.sh   # 7 new tests pass
git add src/dispatchzero/main.py frontend tests/test_frontend_serving.py
git commit -m "feat: serve frontend via FastAPI StaticFiles + SPA fallback"
```

---

### Task 3: Design tokens

**Replace `frontend/static/css/tokens.css`** with the full token set:

- **Surfaces:** `--surface-bg: #0e0c0a` (warm near-black), `--surface-raised: #15120e`, `--surface-rule: #2a2520`
- **Text:** `--text: #e8e1d8` (warm off-white), `--text-muted: #857d72`, `--text-faint: #5a5249`
- **Accent (default + per-style overrides on `body[data-style="..."]`):**
  - default `--accent: #4ec5d6` (cyan), `--accent-dim: #2c7a86`
  - `[data-style="pulp"]` → `--accent: #d68a3c` (amber), `--accent-dim: #7a4d20`
  - `[data-style="agency"]` → `--accent: #4ec5d6` (cyan), `--accent-dim: #2c7a86`
  - `[data-style="guild"]` → `--accent: #7c9a6e` (moss), `--accent-dim: #45593e`
- **Type stacks:** `--font-body` (system-ui), `--font-mono` (JetBrains Mono / Menlo / Consolas / monospace), `--font-serif` (Iowan Old Style / Apple Garamond / Georgia)
- **Type scale:** `--t-xs` 0.75rem, `--t-sm` 0.875rem, `--t-base` 1rem, `--t-lg` 1.125rem, `--t-xl` 1.25rem, `--t-2xl` 1.5rem, `--t-3xl` 2rem
- **Spacing scale:** `--s-1` through `--s-7` (0.25rem step doubling)
- **Radii:** `--r-sm: 2px`, `--r-md: 4px` (almost-square dossier feel)
- **Borders:** `--border-rule: 1px solid var(--surface-rule)`, `--border-accent: 1px solid var(--accent)`
- **Base reset:** `* { box-sizing: border-box }`, `html, body { margin: 0; background: var(--surface-bg); color: var(--text); font-family: var(--font-body); }`. Body is viewport-locked: `overflow: hidden; height: 100dvh; width: 100dvw; overscroll-behavior: none; touch-action: manipulation`.
- **Default styles for `button`** (transparent bg, rule border, hover changes border + text to accent). `.primary` variant (accent border + text, hover inverts). Disabled state.
- **Default styles for `input, select, textarea`** (raised surface, rule border, accent on focus).
- **Default `label`** (uppercase, letter-spaced, muted, small).
- **Utility classes:** `.mono`, `.muted`, `.faint`.

```bash
git add frontend/static/css/tokens.css
git commit -m "feat: dossier design tokens (warm charcoal, per-style accents)"
```

---

### Task 4: Layout primitives (no-scroll viewport-locked frame)

**Replace `frontend/static/css/layout.css`** with:

- `#app { height: 100dvh; width: 100dvw; display: grid; place-items: stretch; }`
- `.screen` is the root of every screen — a CSS-grid frame with three rows (header, content, actions). Max-width 540px (phone-first), centered, full-height, padded.
- `.screen > .header` — flex row with mono uppercase labels, divided by bottom rule
- `.screen > .content` — flex column with gap; default `overflow: hidden` (no-scroll). Add `.scrollable` class for the rare exception (Full Brief in Phase 7).
- `.screen > .actions` — flex column with gap and top rule, pinned to bottom
- Utility blocks: `.field` (label + input column), `.stack` (vertical with gap), `.row` (horizontal with gap), `.divider`, `.code` (mono + accent), `.title`, `.subtitle`, `.handler-mark` (small avatar + label), `.fault` (danger-bordered error block)

```bash
git add frontend/static/css/layout.css
git commit -m "feat: viewport-locked screen layout primitives"
```

---

### Task 5: JS plumbing — `dom.js`, `api.js`, `state.js`, `router.js`

**`frontend/static/js/dom.js`** — single `el(tag, attrs, ...children)` factory:
- `attrs.class` → element.className
- `attrs.onclick` (or any `on*`) → addEventListener
- Other attrs → setAttribute (skip null/undefined)
- Children: strings/numbers become text nodes (safe by construction); arrays are flattened; null/false skipped; otherwise treated as DOM nodes
- Plus `text(s)` helper that returns a text node, for cases where you want to set dynamic text without going through el()

**`frontend/static/js/api.js`** — `request(method, path, { body, formData, headers })` returns `{ ok, status, data }`:
- Uses `credentials: "same-origin"` so the session cookie flows
- JSON-encodes body if provided; passes FormData straight through (browser sets multipart boundary)
- Returns `{ ok: false, status: 401 }` on 401 (caller can route to login). Throws Error with `.status` and `.data` on other non-2xx.
- Exports `api.get(path)`, `api.post(path, body)`, `api.postForm(path, formData)`

**`frontend/static/js/state.js`** — minimal pub/sub user store:
- `_state = { user: null }`
- `getUser()`, `setUser(u)`, `clearUser()`, `onUserChange(fn)` (returns unsubscribe)
- `setUser` ALSO sets `document.body.dataset.style` to `u.adventure_style` (or "agency" default) so theming follows auth state

**`frontend/static/js/router.js`** — 50-LOC client router:
- `defineRoute(path, render)` registers a renderer
- `defineNotFound(render)` for fallback
- `init(rootElement)` — wires `popstate`, intercepts clicks on `a[data-route]`, calls `render(window.location.pathname)`
- `navigate(path, { replace })` pushes/replaces history then renders
- `render(path)` looks up the route, awaits the renderer (which returns an HTMLElement), `replaceChildren()` on root

```bash
git add frontend/static/js/dom.js frontend/static/js/api.js frontend/static/js/state.js frontend/static/js/router.js
git commit -m "feat: JS plumbing (el helper, api wrapper, user state, client router)"
```

---

### Task 6: App bootstrap + splash screen

**`frontend/static/js/screens/splash.js`** — exports `splash()` returning the screen element built via `el()`:
- header: `// dispatch zero //` left, `— receiving` muted right
- content centered: title "Connecting", muted mono "Verifying credentials…"
- empty actions

**`frontend/static/js/app.js`** — entry module:
1. Get `#app` root
2. Paint splash immediately
3. Register service worker (best-effort, swallow errors)
4. Call `api.get("/auth/me")`:
   - On 200: `setUser(data)`
   - On 401: `clearUser()`
5. Define routes:
   - `/` → if user, `home()`; else `anonLanding()`
   - `/signup` → `signup()`
   - `/login` → `login()`
   - `/style` → `stylePicker()`
6. `init(root)` — first render fires from current pathname

`anonLanding()` lives in app.js — small screen with title "No active credentials" and two buttons: "Apply for Field Status" (→ /signup), "I have credentials" (→ /login).

```bash
git add frontend/static/js/app.js frontend/static/js/screens/splash.js
git commit -m "feat: app bootstrap with auth-state branching + splash screen"
```

---

### Task 7: Signup screen

**`frontend/static/js/screens/signup.js`** — exports `signup()` returning a `<form class="screen">` built via `el()`:

**Header:** `// dispatch zero //` + `— application`

**Content:**
- Title "Apply for Field Status"
- Muted helper text: "Choose a callsign and a passphrase. The Archive does not issue replacements — memorize what you set here."
- Field: callsign input — `pattern="[a-zA-Z0-9_-]+"`, minlength 3, maxlength 32, autocomplete "username", required
- Field: password input — type password, minlength 8, maxlength 128, autocomplete "new-password", required
- Field: adventure_style select with three options:
  - `agency` — "Agency — clinical, classified directives"
  - `pulp` — "Pulp — expeditionary, warm"
  - `guild` — "Guild — ancient, ceremonial"
- Hidden `.fault` div for error display

**Actions:**
- Primary submit button "Submit Application"
- Muted link to `/login` data-route: "Already have credentials?"

**Submit handler:**
- `e.preventDefault()`, hide error, disable button
- Read FormData, `api.post("/auth/signup", { callsign, password, adventure_style })`
- On `{ok: true}`: `setUser(data)`, `navigate("/", { replace: true })`
- Else: show error message in `.fault` (text from `data?.detail` or generic "Application denied.")
- Always re-enable button in finally

```bash
git add frontend/static/js/screens/signup.js
git commit -m "feat: signup screen"
```

---

### Task 8: Login screen

**`frontend/static/js/screens/login.js`** — same structure as signup but:
- Title "Resume Field Status"
- Two fields only (callsign, password — no style)
- Submit hits `/auth/login`
- On 401, error message: "Credentials not recognized, agent."
- Muted link to `/signup`: "Apply for new field status"

```bash
git add frontend/static/js/screens/login.js
git commit -m "feat: login screen"
```

---

### Task 9: Home screen

**`frontend/static/js/screens/home.js`** — exports async `home()`:

1. Re-fetch `/auth/me` (so completions_count is fresh on every visit). On 401: clearUser + navigate("/login", replace), return empty div.
2. setUser(fresh data)
3. Build screen:

**Header:** `// dispatch zero //` left, `<callsign>` in `.code` style right

**Content:**
- Row: avatar (`<img src="/static/avatars/zero-{style}.png">` 64×64 circular, bordered) + small column with subtitle "handler", title "Zero", muted mono style label like "PULP // THE ARCHIVE"
- Divider
- Stack with two metric rows:
  - "Completions" subtitle ↔ big `.code` number (text-2xl)
  - "This week" subtitle ↔ `.code` number
- Divider
- Row: "Change style" link (→ `/style`) ↔ "Stand down" link

**Actions:**
- Primary "Request Dispatch" button — disabled in Phase 6 (Phase 7 wires it)
- Muted mono caption: "Mission flow lands in Phase 7."

**Logout handler:** `api.post("/auth/logout", {})`, `clearUser()`, `navigate("/", { replace: true })`

```bash
git add frontend/static/js/screens/home.js
git commit -m "feat: home screen with avatar, metrics, logout"
```

---

### Task 10: Style switcher (frontend + new backend endpoint)

**Backend first.** In `src/dispatchzero/auth/routes.py` add:

```python
class StyleIn(BaseModel):
    adventure_style: AdventureStyle  # imported from schemas.auth


@router.post("/style", response_model=MeOut)
async def change_style(
    payload: StyleIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> MeOut:
    user.adventure_style = payload.adventure_style
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return await _user_to_me(db, user)
```

Add to `tests/test_auth_routes.py`:
- `test_change_style` — signup, post /auth/style with new style, assert 200 + new style in response
- `test_change_style_requires_auth` — clear cookies, post /auth/style, assert 401

`./deploy/test.sh` — verify pass.

**Frontend.** `frontend/static/js/screens/style-picker.js` — exports `stylePicker()`:
- Header: `// dispatch zero //` + `— style`
- Content: title "Operating Style", muted helper "Style controls Zero's voice, tone, and visual register. Switching does not affect completion history."
- For each of `["pulp", "agency", "guild"]`: a button (data-attribute `data-style-choice`), `.primary` class if it matches the current user style. Inside the button: subtitle (style label like "AGENCY // CLASSIFIED") and a normal-text description.
- Hidden `.fault` for errors.
- Actions: muted "Back to Home" link to `/`.
- Click handler on each style button: `api.post("/auth/style", { adventure_style: choice })`. On success: setUser(data), navigate("/", {replace:true}). On error: show `.fault`.

Register the route in `app.js`: `defineRoute("/style", () => stylePicker())`.

```bash
git add src/dispatchzero/auth/routes.py tests/test_auth_routes.py frontend/static/js/screens/style-picker.js frontend/static/js/app.js
git commit -m "feat: POST /auth/style + style picker screen"
```

---

### Task 11: Deploy + browser verify

```bash
./deploy/deploy.sh
```

**Browser checks (Trevor on his phone, against `https://dispatchzero.ataary.com`):**
1. App loads to anon landing ("No active credentials").
2. Sign up with a fresh callsign+password+style → lands on Home with the right avatar (Zero in chosen style) and counters at 0.
3. Logout → returns to anon landing.
4. Login with just-created credentials → Home.
5. "Change style" → picker, select different style → Home with new avatar + accent color.
6. Browser shows install prompt (Safari Share menu "Add to Home Screen", or Chrome install icon).
7. DevTools > Application > Service Workers shows "activated and running".

**Static asset check:**
```bash
curl -sI https://dispatchzero.ataary.com/static/css/tokens.css | head -10
curl -sI https://dispatchzero.ataary.com/static/avatars/zero-agency.png | head -10
```

Both should return 200 with proper content-type.

**Cleanup test users** (use the `phase6_` prefix while testing so this is clean):
```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d dispatchzero -c \"DELETE FROM users WHERE callsign_lower LIKE 'phase6%';\""
```

**Final health:**
```bash
ssh root@89.167.39.152 "systemctl is-active paperclip.service && free -h | head -2 && df -h /"
```

---

## Phase 6 — Definition of Done

- All backend tests pass (existing 126 + 7 new frontend-serving + 2 new auth/style = 135).
- Production loads `https://dispatchzero.ataary.com` to a working SPA.
- Real signup → Home flow works on a phone.
- Login persists across page refresh (cookie holds).
- Logout returns to anon landing.
- Style switch swaps avatar + accent color in real time.
- PWA install prompt offered on at least one mobile browser.
- Service worker activated.
- Three Zero avatars reachable at `/static/avatars/zero-{pulp,agency,guild}.png`.
- Paperclip restart count unchanged.

---

## Critical Files To Be Created In Phase 6

| File | Purpose |
|---|---|
| `frontend/index.html` | App shell |
| `frontend/manifest.webmanifest` | PWA install metadata |
| `frontend/service-worker.js` | Cache shell + network-first API |
| `frontend/favicon.svg` | Placeholder favicon |
| `frontend/static/css/{tokens,layout,screens}.css` | Design tokens, layout primitives, per-screen tweaks |
| `frontend/static/js/{app,router,api,state,dom}.js` | JS plumbing (no framework) |
| `frontend/static/js/screens/{splash,signup,login,home,style-picker}.js` | The five Phase 6 screens |
| `frontend/static/avatars/zero-{pulp,agency,guild}.png` | Handler avatars |
| `src/dispatchzero/main.py` (mod) | StaticFiles mount + SPA fallback |
| `src/dispatchzero/auth/routes.py` (mod) | + POST /auth/style |
| `tests/test_frontend_serving.py` | Static + SPA fallback tests |

---

## Open Decisions

| Decision | Default | Where to change |
|---|---|---|
| Frontend stack | Vanilla JS modules | If Phase 7+ demand richer state, swap to Lit or Preact |
| Routing | 50-LOC custom router | Replace with library only on real friction |
| PWA icon | `zero-agency.png` | Dedicated logo in Phase 12 |
| Service worker scope | Shell only | Add offline mission cards in Phase 9 |
| Style switcher endpoint | `POST /auth/style` | Could be `PATCH /auth/me` for REST purity; not worth bikeshedding |
| Avatar resizing | Ship as-is | Optimize in Phase 12 |
| `frontend/` in git | Yes | We don't have a CDN; deploy bundles assets |

---

## What Comes Next

**Phase 7 — Mission UI screens.** With the shell, design tokens, layout primitives, and auth flow in place, Phase 7 plugs in the seven mission flow screens. At end of Phase 7 the app is launchable on a real phone. Phase 7 picks up the device-API work (DeviceOrientationEvent, geolocation.watchPosition, native camera intent via `<input capture>`).
