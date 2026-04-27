import { el } from "../dom.js";
import { api } from "../api.js";

const BANNER_STYLE = {
  backgroundColor: "var(--warn-surface)",
  color: "var(--warn)",
  padding: "var(--s-1)",
  textAlign: "center",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--t-xs)",
  letterSpacing: "0.05em",
  justifyContent: "center",
};

export function betaBannerEl() {
  return el("div", { class: "row", style: BANNER_STYLE }, "// BETA — closed pilot //");
}

// Splash is the initial paint shown while the bootstrap auth check runs. It
// must return synchronously so app.js can paint immediately. The /config fetch
// for the BETA banner happens in the background and prepends the banner to
// the content zone when (and if) it resolves before the screen is replaced.
export function splash() {
  const content = el("div",
    { class: "content", style: { justifyContent: "center", alignItems: "center" } },
    el("div", { class: "title" }, "Connecting"),
    el("div", { class: "muted mono" }, "Verifying credentials…"),
  );

  // Fire-and-forget — render without banner if /config fails or the splash
  // is replaced before this resolves.
  (async () => {
    try {
      const r = await api.get("/config");
      if (r.ok && r.data && r.data.show_beta_banner) {
        content.insertBefore(betaBannerEl(), content.firstChild);
      }
    } catch { /* ignore */ }
  })();

  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "— receiving"),
    ),
    content,
    el("div", { class: "actions" }),
  );
}
