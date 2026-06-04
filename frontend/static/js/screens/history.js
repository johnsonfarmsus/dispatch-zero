// Dossier — the user's missions and community submissions, merged into one
// list ordered by date (newest first). Each row is a tappable card.
//
// Both kinds carry the same conceptual artifact (a card with their photo +
// the place's name + a date), so they share the row component. The only
// visual difference is the row's image source, the tap target, and a status
// badge on submissions that aren't APPROVED.
import { api } from "../api.js";
import { el } from "../dom.js";

const _STATUS_BADGE = {
  pending: { label: "PENDING", color: "var(--text-muted)" },
  approved: null,  // approved submissions read as regular completions in the list
  returned: { label: "RETURNED", color: "var(--danger)" },
};

export async function history() {
  // Fetch both endpoints in parallel. A failure on either still surfaces what
  // we have from the other.
  const [missions, submissions] = await Promise.all([
    api.get("/missions/completions"),
    api.get("/submissions"),
  ]);

  if (!missions.ok && !submissions.ok) {
    return _errorScreen("Dossier unavailable.", "Try again in a moment, agent.");
  }

  const items = _merge(missions.data || [], submissions.data || []);

  const list = items.length === 0
    ? el("div", { class: "muted", style: { padding: "var(--s-3) 0" } },
        "No completed dispatches yet, agent. Request your first one or report a Point of Interest from Home.")
    : el("div", { class: "stack", style: { gap: "var(--s-2)" } },
        ...items.map((it) => historyRow(it)));

  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "dossier"),
    ),
    el("div", { class: "content stack" },
      el("div", { class: "subtitle" }, "DOSSIER"),
      el("div", { class: "title", style: { fontSize: "var(--t-xl)" } },
        `${items.length} entr${items.length === 1 ? "y" : "ies"} on file`),
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


// Normalize the two payload shapes into a single dossier-item shape:
//   { kind, id, date, name, category, route, image_src, status }
// where status is null for missions and one of pending/approved/returned for
// submissions. Then sort newest-first.
function _merge(missions, submissions) {
  const m = missions.map((c) => ({
    kind: "mission",
    id: c.id,
    date: c.completed_at,
    name: c.place_name,
    category: c.place_category,
    route: `/history/${c.id}`,
    image_src: `/missions/completions/${c.id}/photo.jpg`,
    status: null,
  }));
  const s = submissions.map((sub) => ({
    kind: "submission",
    id: sub.id,
    date: sub.submitted_at,
    name: sub.place_name,
    category: sub.place_category,
    route: `/submission/${sub.id}`,
    image_src: `/submissions/${sub.id}/photo.jpg`,
    status: sub.status,
  }));
  return [...m, ...s].sort((a, b) => {
    // Lexical sort works on ISO 8601 strings (both endpoints emit ISO). Use
    // descending so newest is first.
    return a.date < b.date ? 1 : a.date > b.date ? -1 : 0;
  });
}


function historyRow(it) {
  const date = new Date(it.date);
  const dateStr = date.toLocaleDateString(undefined, {
    year: "numeric", month: "short", day: "numeric",
  });
  const badgeSpec = it.kind === "submission" ? _STATUS_BADGE[it.status] : null;
  const subtitle = `${(it.category || "").toUpperCase()} · ${dateStr}`;

  return el("a", {
    href: it.route,
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
      src: it.image_src,
      alt: "",
      style: {
        width: "64px", height: "64px", objectFit: "cover",
        borderRadius: "var(--r-sm)", flex: "0 0 auto",
      },
    }),
    el("div", { class: "stack", style: { gap: "2px", flex: "1 1 auto", minWidth: "0" } },
      el("div", { class: "row", style: { gap: "var(--s-2)", alignItems: "baseline" } },
        el("div", {
          style: {
            fontSize: "var(--t-base)", fontWeight: "600",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            flex: "1 1 auto", minWidth: "0",
          },
        }, it.name || "Unmarked target"),
        badgeSpec
          ? el("span", {
              class: "mono",
              style: {
                fontSize: "var(--t-xs)",
                letterSpacing: "0.08em",
                color: badgeSpec.color,
                border: `1px solid ${badgeSpec.color}`,
                borderRadius: "var(--r-sm)",
                padding: "1px 6px",
                flex: "0 0 auto",
              },
            }, badgeSpec.label)
          : null,
      ),
      el("div", { class: "muted mono", style: { fontSize: "var(--t-xs)" } },
        subtitle),
    ),
  );
}


function _errorScreen(title, msg) {
  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "dossier"),
    ),
    el("div", { class: "content stack" },
      el("div", { class: "title" }, title),
      el("div", { class: "muted" }, msg),
    ),
    el("div", { class: "actions" },
      el("a", { href: "/", "data-route": true, class: "muted",
                style: { textAlign: "center", padding: "var(--s-2)" } },
        "← Back to Home"),
    ),
  );
}
