// Dossier — list of the user's recent completions, newest first.
// Tap a row to open the per-completion review screen.
import { api } from "../api.js";
import { el } from "../dom.js";
import { navigate } from "../router.js";

export async function history() {
  const r = await api.get("/missions/completions");
  if (!r.ok) {
    return el("div", { class: "screen" },
      el("div", { class: "header" },
        el("span", {}, "// dispatch zero //"),
        el("span", { class: "muted" }, "— dossier"),
      ),
      el("div", { class: "content stack" },
        el("div", { class: "title" }, "Dossier unavailable."),
        el("div", { class: "muted" }, "Try again in a moment, agent."),
      ),
      el("div", { class: "actions" },
        el("a", { href: "/", "data-route": true, class: "muted",
                  style: { textAlign: "center", padding: "var(--s-2)" } },
          "← Back to Home"),
      ),
    );
  }

  const items = r.data || [];
  const list = items.length === 0
    ? el("div", { class: "muted", style: { padding: "var(--s-3) 0" } },
        "No completed dispatches yet, agent. Request your first one from Home.")
    : el("div", { class: "stack", style: { gap: "var(--s-2)" } },
        ...items.map((c) => historyRow(c)));

  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "— dossier"),
    ),
    el("div", { class: "content stack" },
      el("div", { class: "subtitle" }, "DOSSIER"),
      el("div", { class: "title", style: { fontSize: "var(--t-xl)" } },
        `${items.length} dispatch${items.length === 1 ? "" : "es"} on file`),
      el("div", { class: "divider" }),
      list,
    ),
    el("div", { class: "actions" },
      el("a", { href: "/", "data-route": true, class: "muted",
                style: { textAlign: "center", padding: "var(--s-2)" } },
        "← Back to Home"),
    ),
  );
}

function historyRow(c) {
  const date = new Date(c.completed_at);
  const dateStr = date.toLocaleDateString(undefined, {
    year: "numeric", month: "short", day: "numeric",
  });
  const row = el("a", {
    href: `/history/${c.id}`,
    "data-route": true,
    class: "row",
    style: {
      gap: "var(--s-3)",
      padding: "var(--s-2)",
      border: "1px solid var(--surface-rule)",
      borderRadius: "var(--r-sm)",
      textDecoration: "none",
      color: "inherit",
      alignItems: "center",
    },
  },
    el("img", {
      src: `/missions/completions/${c.id}/photo.jpg`,
      alt: "",
      style: {
        width: "64px", height: "64px", objectFit: "cover",
        borderRadius: "var(--r-sm)", flex: "0 0 auto",
      },
    }),
    el("div", { class: "stack", style: { gap: "2px", flex: "1 1 auto", minWidth: "0" } },
      el("div", {
        style: {
          fontSize: "var(--t-base)", fontWeight: "600",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        },
      }, c.place_name || "Unmarked target"),
      el("div", { class: "muted mono", style: { fontSize: "var(--t-xs)" } },
        `${(c.place_category || "").toUpperCase()} · ${dateStr}`),
    ),
  );
  return row;
}
