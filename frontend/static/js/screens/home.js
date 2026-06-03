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

  const requestBtn = el("button", { class: "primary" }, "Request Dispatch");
  const requestStatus = el("div", {
    class: "muted mono",
    style: { textAlign: "center", fontSize: "var(--t-xs)" },
  }, "");

  // Two prominent secondary buttons in the dead space between stats and the
  // primary Request Dispatch action. The kebab menu these replace was
  // discoverable but under-used — surfacing the two highest-traffic screens
  // (dossier + style switch) as actual buttons is a UX upgrade.
  const historyBtn = el("a", {
    href: "/history", "data-route": true,
    class: "secondary-action",
  }, "History");
  const settingsBtn = el("a", {
    href: "/style", "data-route": true,
    class: "secondary-action",
  }, "Settings");

  const screen = el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "code" }, user.callsign),
    ),
    // Single-page gameplay screen — no scroll. The whole action stack
    // (History/Settings, Report, Request Dispatch) lives in the content
    // area as one tight group; the actions footer below holds only the
    // small security-protocols policy link. Tightened content stack gap
    // (--s-3, default --s-5) keeps everything within the in-browser
    // viewport.
    el("div", { class: "content stack", style: { gap: "var(--s-3)" } },
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
      // Tighter dividers on this screen — the default .divider has
      // var(--s-4) margin top+bottom which adds ~32px each; we want the
      // sections to read as a unit, so cut to var(--s-2).
      el("div", { class: "divider", style: { margin: "var(--s-2) 0" } }),
      // Callsign hero — restored above the stats but without the AGENT
      // subtitle (label was redundant with the // dispatch zero // —
      // CALLSIGN band in the header). The big mono treatment still gives
      // the operative a personal-card moment without the duplicate prose.
      el("div", { style: { textAlign: "center" } },
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
          // Completions count + a small "(N pending)" suffix when the user has
          // community submissions awaiting review. Pending submissions roll
          // into the main count when approved; the suffix is the visual
          // signal that a count change is in flight.
          el("div", { class: "row", style: { gap: "var(--s-2)", alignItems: "baseline" } },
            el("span", { class: "code", style: { fontSize: "var(--t-2xl)" } },
              String(user.completions_count ?? 0)),
            (user.pending_submissions ?? 0) > 0
              ? el("span", {
                  class: "muted mono",
                  style: { fontSize: "var(--t-xs)" },
                }, `(${user.pending_submissions} pending)`)
              : null,
          ),
        ),
        el("div", { class: "row", style: { justifyContent: "space-between" } },
          el("span", { class: "subtitle" }, "This week"),
          el("span", { class: "code" }, String(user.missions_this_week ?? 0)),
        ),
      ),
      el("div", { class: "divider", style: { margin: "var(--s-2) 0" } }),
      // History + Settings: secondary actions in the dead space between
      // stats and Request Dispatch. Equal-width 50/50.
      el("div", {
        class: "row",
        style: {
          gap: "var(--s-3)",
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
        },
      },
        historyBtn,
        settingsBtn,
      ),
      // Report button — sits in the same stack as History/Settings AND
      // Request Dispatch below. The whole action group reads as one
      // visually tight unit.
      el("a", {
        href: "/report", "data-route": true,
        class: "secondary-action",
      }, "Report a Point of Interest"),
      // Request Dispatch — primary action. Lives in the content stack
      // (not the actions footer) so the gap above it is just the content
      // stack's --s-3 rather than the actions area's border-top +
      // padding-top + screen grid gap (~35px of extra separation that
      // would visually orphan it from the buttons above).
      requestBtn,
      requestStatus,
    ),
    // Bottom row of the screen grid. Used to be a .actions wrapper but
    // that class carries a border-top that drew an unwanted line under
    // Request Dispatch. A plain div fills the grid slot without the line;
    // grid pinning still anchors the security link to the bottom of the
    // viewport.
    el("div", { style: { display: "flex", flexDirection: "column" } },
      el("a", {
        href: "/security", "data-route": true,
        class: "muted",
        style: {
          textAlign: "center",
          fontSize: "var(--t-xs)",
          textTransform: "uppercase",
          letterSpacing: "0.12em",
        },
      }, "// security protocols //"),
    ),
  );

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

  return screen;
}
