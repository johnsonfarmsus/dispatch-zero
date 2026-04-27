import { el } from "../dom.js";
import { api } from "../api.js";
import { getUser, setUser } from "../state.js";
import { navigate } from "../router.js";
import { STYLE_META } from "../style-meta.js";

export function stylePicker() {
  const current = getUser()?.adventure_style || "agency";
  const errEl = el("div", { class: "fault", hidden: true });

  function styleOption(s) {
    const isCurrent = s === current;
    const meta = STYLE_META[s];
    const btn = el("button", {
      class: isCurrent ? "primary" : "",
      style: {
        textAlign: "left",
        padding: "var(--s-4)",
        display: "flex",
        flexDirection: "column",
        gap: "var(--s-2)",
      },
    },
      el("div", { class: "row", style: { justifyContent: "space-between", alignItems: "baseline" } },
        el("span", { class: "subtitle" }, meta.org),
        el("span", { class: "muted mono", style: { fontSize: "var(--t-xs)" } },
          isCurrent ? "CURRENT" : ""),
      ),
      el("span", {
        style: {
          color: "var(--text)",
          fontFamily: "var(--font-serif)",
          lineHeight: "1.5",
        },
      }, meta.tone),
      el("span", { class: "muted mono", style: { fontSize: "var(--t-xs)" } },
        `Handler: ${meta.handler}`),
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
      el("span", { class: "muted" }, "— organization"),
    ),
    el("div", { class: "content stack scrollable" },
      el("div", { class: "title" }, "Choose Your Organization"),
      el("div", { class: "muted" },
        "Three organizations dispatch you to the same real places. Each has its own handler, its own tone, its own way of asking. Switching does not affect what you've already documented.",
      ),
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
    ),
  );
}
