import { el } from "../dom.js";
import { api } from "../api.js";
import { setUser, clearUser } from "../state.js";
import { navigate } from "../router.js";
import { getFreshFix, clearMissionCache, clearLastDebrief } from "../flow.js";

const STYLE_LABEL = {
  pulp:   "PULP // THE ARCHIVE",
  agency: "AGENCY // CLASSIFIED",
  guild:  "GUILD // CEREMONIAL",
};

export async function home() {
  const r = await api.get("/auth/me");
  if (!r.ok) {
    clearUser();
    await navigate("/login", { replace: true });
    return el("div");
  }
  const user = r.data;
  setUser(user);

  const logoutLink = el("a", { href: "#", class: "muted" }, "Stand down");
  const requestBtn = el("button", { class: "primary" }, "Request Dispatch");
  const requestStatus = el("div", {
    class: "muted mono",
    style: { textAlign: "center", fontSize: "var(--t-xs)" },
  }, "");

  const screen = el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "code" }, user.callsign),
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
          el("div", { class: "title", style: { fontSize: "var(--t-xl)" } }, "Zero"),
          el("div", {
            class: "muted mono",
            style: { fontSize: "var(--t-xs)" },
          }, STYLE_LABEL[user.adventure_style] || user.adventure_style),
        ),
      ),
      el("div", { class: "divider" }),
      el("div", { class: "stack", style: { gap: "var(--s-2)" } },
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
      el("div", { class: "divider" }),
      el("div", { class: "row", style: { justifyContent: "space-between" } },
        el("a", { href: "/style", "data-route": true, class: "muted" }, "Change style"),
        logoutLink,
      ),
    ),
    el("div", { class: "actions" },
      requestBtn,
      requestStatus,
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
      const fix = await getFreshFix({ maxAgeMs: 30000 });
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
      const msg = e.message || "Dispatch failed.";
      if (e.code === e.PERMISSION_DENIED || /denied|geolocation/i.test(msg)) {
        requestStatus.textContent = "Location permission required, agent.";
      } else if (e.status === 404) {
        requestStatus.textContent = "No eligible targets within 2 km.";
      } else if (e.status === 503) {
        requestStatus.textContent = "Dispatch line is unreliable. Try again.";
      } else {
        requestStatus.textContent = msg;
      }
      requestBtn.disabled = false;
    }
  });

  return screen;
}
