import { el } from "../dom.js";
import { api } from "../api.js";
import { getUser, setUser, clearUser } from "../state.js";
import { navigate } from "../router.js";
import { STYLE_META } from "../style-meta.js";

// Short, viewport-friendly taglines per org. The longer prose lives in
// STYLE_META.tone; this picker stays terse so the screen fits without scroll.
const TAGLINES = {
  pulp: "Warm, curious, expedition energy.",
  agency: "Cold, classified, professional.",
  guild: "Ancient, ceremonial, formal.",
};

export function stylePicker() {
  const current = getUser()?.adventure_style || "agency";
  const errEl = el("div", { class: "fault", hidden: true });
  const logoutLink = el("a", { href: "#", class: "muted" }, "Stand Down");
  logoutLink.addEventListener("click", async (e) => {
    e.preventDefault();
    await api.post("/auth/logout", {});
    clearUser();
    await navigate("/", { replace: true });
  });

  function styleOption(s) {
    const isCurrent = s === current;
    const meta = STYLE_META[s];
    const btn = el("button", {
      class: isCurrent ? "primary" : "",
      style: {
        textAlign: "left",
        padding: "var(--s-3)",
        display: "flex",
        flexDirection: "column",
        gap: "2px",
      },
    },
      el("div", { class: "row", style: { justifyContent: "space-between", alignItems: "baseline" } },
        el("span", { class: "subtitle" }, meta.org),
        el("span", { class: "muted mono", style: { fontSize: "var(--t-xs)" } },
          isCurrent ? "CURRENT" : ""),
      ),
      el("span", {
        style: { color: "var(--text)", fontSize: "var(--t-sm)" },
      }, TAGLINES[s] || ""),
    );
    btn.addEventListener("click", async () => {
      if (isCurrent) return;
      errEl.hidden = true;
      try {
        const r = await api.post("/auth/style", { adventure_style: s });
        if (r.ok) {
          setUser(r.data);
          await navigate("/", { replace: true });
          return;
        }
        throw new Error(r.data?.detail || "Style change failed.");
      } catch (e) {
        errEl.textContent = e.message;
        errEl.hidden = false;
      }
    });
    return btn;
  }

  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "— settings"),
    ),
    el("div", { class: "content stack" },
      el("div", { class: "subtitle" }, "Organization"),
      styleOption("pulp"),
      styleOption("agency"),
      styleOption("guild"),
      errEl,
    ),
    el("div", { class: "actions" },
      el("a", {
        href: "/", "data-route": true, class: "muted",
        style: { textAlign: "center", padding: "var(--s-2)" },
      }, "Back to Home"),
      // Account action — lives here in Settings rather than on the main
      // dashboard, where it was easy to misfire near the Request Dispatch
      // button.
      logoutLink,
    ),
  );
}
