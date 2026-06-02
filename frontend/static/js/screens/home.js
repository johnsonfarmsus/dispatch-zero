import { el } from "../dom.js";
import { api } from "../api.js";
import { setUser, clearUser } from "../state.js";
import { navigate } from "../router.js";
import { getFreshFix, clearMissionCache, clearLastDebrief } from "../flow.js";
import { styleMeta, rankName } from "../style-meta.js";

export async function home() {
  const r = await api.get("/auth/me");
  if (!r.ok) {
    clearUser();
    await navigate("/login", { replace: true });
    return el("div");
  }
  const user = r.data;
  setUser(user);

  const logoutLink = el("a", { href: "#", class: "muted" }, "Stand Down");
  const requestBtn = el("button", { class: "primary" }, "Request Dispatch");
  const requestStatus = el("div", {
    class: "muted mono",
    style: { textAlign: "center", fontSize: "var(--t-xs)" },
  }, "");

  const menu = navMenu();

  const screen = el("div", { class: "screen" },
    el("div", { class: "header", style: { position: "relative" } },
      el("span", {}, "// dispatch zero //"),
      el("div", { class: "row", style: { gap: "var(--s-3)" } },
        el("span", { class: "code" }, user.callsign),
        menu.button,
      ),
      menu.panel,
    ),
    el("div", { class: "content stack" },
      el("div", { class: "row" },
        el("img", {
          src: `/static/avatars/zero-${user.adventure_style}.png`,
          alt: `Zero — ${user.adventure_style} style`,
          style: {
            width: "64px", height: "64px", borderRadius: "50%",
            border: "1px solid var(--surface-rule)", objectFit: "cover",
          },
        }),
        el("div", {},
          el("div", { class: "subtitle" }, "handler"),
          el("div", { class: "title", style: { fontSize: "var(--t-xl)" } },
            styleMeta(user.adventure_style).handler),
          el("div", { class: "muted", style: { fontStyle: "italic" } },
            styleMeta(user.adventure_style).org),
        ),
      ),
      el("div", { class: "divider" }),
      el("div", { class: "stack", style: { gap: "var(--s-2)", alignItems: "center" } },
        el("span", { class: "subtitle" }, "Agent"),
        el("span", {
          class: "code",
          style: { fontSize: "var(--t-2xl)", letterSpacing: "0.04em" },
        }, user.callsign),
      ),
      el("div", { class: "stack", style: { gap: "var(--s-2)" } },
        el("div", { class: "row", style: { justifyContent: "space-between" } },
          el("span", { class: "subtitle" }, "Rank"),
          el("span", { class: "code", style: { fontSize: "var(--t-lg)" } },
            rankName(user.adventure_style, user.rank)),
        ),
        el("div", { class: "row", style: { justifyContent: "space-between" } },
          el("span", { class: "subtitle" }, "Completions"),
          el("span", { class: "code", style: { fontSize: "var(--t-2xl)" } },
            String(user.completions_count ?? 0)),
        ),
        el("div", { class: "row", style: { justifyContent: "space-between" } },
          el("span", { class: "subtitle" }, "This week"),
          el("span", { class: "code" }, String(user.missions_this_week ?? 0)),
        ),
      ),
    ),
    el("div", { class: "actions" },
      requestBtn,
      requestStatus,
      logoutLink,
    ),
  );

  logoutLink.addEventListener("click", async (e) => {
    e.preventDefault();
    await api.post("/auth/logout", {});
    clearUser();
    await navigate("/", { replace: true });
  });

  requestBtn.addEventListener("click", async () => {
    requestBtn.disabled = true;
    requestStatus.style.color = "var(--text-muted)";
    requestStatus.textContent = "Acquiring fix…";
    try {
      // Coarse fix is fine here — we just need to know the neighborhood
      // to find places within 2km. Capture screen uses high accuracy.
      const fix = await getFreshFix({
        maxAgeMs: 60000,
        enableHighAccuracy: false,
        timeoutMs: 30000,
      });
      requestStatus.textContent = "Acquiring target…";
      const r = await api.post("/missions/request", {
        lat: fix.lat,
        lng: fix.lng,
        radius_m: 2000,
      });
      if (r.ok) {
        clearMissionCache();
        clearLastDebrief();
        await navigate(`/mission/${r.data.id}/dispatch`);
        return;
      }
      throw new Error(r.data?.detail || "Dispatch line is unreliable.");
    } catch (e) {
      requestStatus.style.color = "var(--danger)";
      // GeolocationPositionError has numeric .code AND a PERMISSION_DENIED constant
      // on the instance — that's how we tell it apart from a generic Error.
      if (e && typeof e.code === "number" && typeof e.PERMISSION_DENIED === "number") {
        if (e.code === 1) {
          requestStatus.textContent = "Location access denied. Allow location in your browser settings.";
        } else if (e.code === 2) {
          requestStatus.textContent = "GPS unavailable here. Try outdoors and try again.";
        } else if (e.code === 3) {
          requestStatus.textContent = "GPS fix timed out. Try again, agent.";
        } else {
          requestStatus.textContent = `Location error (${e.code}): ${e.message || "unknown"}`;
        }
      } else if (e.status === 404) {
        requestStatus.textContent =
          "No eligible targets within reach. Try a town with more landmarks, agent.";
      } else if (e.status === 503) {
        requestStatus.textContent = "Dispatch line is unreliable. Try again.";
      } else {
        requestStatus.textContent = e.message || "Dispatch failed.";
      }
      requestBtn.disabled = false;
    }
  });

  return { element: screen, cleanup: menu.cleanup };
}

// Header overflow menu: kebab toggle + absolutely-positioned panel.
// Uses existing tokens (mono uppercase, surface-rule borders, accent on hover)
// so it visually matches the header it lives in.
function navMenu() {
  const button = el("button", {
    "aria-label": "Menu",
    "aria-haspopup": "true",
    "aria-expanded": "false",
    style: {
      padding: "var(--s-1) var(--s-3)",
      fontSize: "var(--t-lg)",
      lineHeight: "1",
      letterSpacing: "0.1em",
    },
  }, "⋮");  // vertical ellipsis (kebab)

  function item(label, href) {
    return el("a", {
      href, "data-route": true,
      style: {
        display: "block",
        padding: "var(--s-3) var(--s-4)",
        color: "var(--text)",
        fontFamily: "var(--font-mono)",
        fontSize: "var(--t-xs)",
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        textDecoration: "none",
        borderBottom: "1px solid var(--surface-rule)",
      },
    }, label);
  }

  const panel = el("div", {
    role: "menu",
    hidden: true,
    style: {
      position: "absolute",
      top: "100%",
      right: "0",
      marginTop: "var(--s-2)",
      minWidth: "180px",
      background: "var(--surface-raised)",
      border: "1px solid var(--surface-rule)",
      borderRadius: "var(--r-sm)",
      zIndex: "10",
    },
  },
    item("Dossier", "/history"),
    item("Switch organization", "/style"),
    item("Security protocols", "/security"),
  );
  // Last item: drop the divider border for a tidier edge.
  panel.lastChild.style.borderBottom = "none";

  function close() {
    panel.hidden = true;
    button.setAttribute("aria-expanded", "false");
  }
  function toggle() {
    const open = panel.hidden;
    panel.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
  }

  button.addEventListener("click", (e) => {
    e.stopPropagation();
    toggle();
  });
  // Click outside closes the menu. The router intercepts data-route link
  // clicks before they reach document, so internal nav still works.
  const onDocClick = (e) => {
    if (panel.hidden) return;
    if (panel.contains(e.target) || button.contains(e.target)) return;
    close();
  };
  // Esc to dismiss — keyboard parity with native menus.
  const onKeydown = (e) => {
    if (e.key === "Escape" && !panel.hidden) close();
  };
  document.addEventListener("click", onDocClick);
  document.addEventListener("keydown", onKeydown);

  const cleanup = () => {
    document.removeEventListener("click", onDocClick);
    document.removeEventListener("keydown", onKeydown);
  };

  return { button, panel, cleanup };
}
