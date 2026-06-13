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
  // Fetch in parallel. A failure on any still surfaces what we have.
  const [missions, submissions, badges] = await Promise.all([
    api.get("/missions/completions"),
    api.get("/submissions"),
    api.get("/badges"),
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
    el("div", { class: "content stack scrollable" },
      el("div", { class: "subtitle" }, "DOSSIER"),
      el("div", { class: "title", style: { fontSize: "var(--t-xl)" } },
        `${items.length} entr${items.length === 1 ? "y" : "ies"} on file`),
      badges.ok ? badgesSection(badges.data) : null,
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


// Badge collection — a collapsible grid showing earned badges bright and
// locked ones dimmed with a small progress count. Computed server-side from
// completion history (GET /badges). Collapsed by default so it doesn't push
// the dossier list down; the summary line ("Badges 4/14") is the toggle.
function badgesSection(data) {
  if (!data || !Array.isArray(data.badges) || data.badges.length === 0) {
    return null;
  }
  const grid = el("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(96px, 1fr))",
      gap: "var(--s-2)",
      marginTop: "var(--s-2)",
    },
  }, ...data.badges.map(badgeChip));

  // Collapsed by default.
  grid.style.display = "none";
  let open = false;

  const caret = el("span", { class: "muted mono", style: { fontSize: "var(--t-xs)" } }, "▸");
  const toggle = el("button", {
    style: {
      width: "100%", textAlign: "left", display: "flex",
      justifyContent: "space-between", alignItems: "center",
      border: "1px solid var(--surface-rule)", borderRadius: "var(--r-sm)",
      padding: "var(--s-2) var(--s-3)", background: "var(--surface-raised)",
    },
  },
    el("span", { class: "subtitle", style: { color: "var(--text)" } }, "Badges"),
    el("span", { class: "row", style: { gap: "var(--s-2)", alignItems: "center" } },
      el("span", { class: "code", style: { fontSize: "var(--t-sm)" } },
        `${data.earned_count}/${data.total_count}`),
      caret,
    ),
  );
  toggle.addEventListener("click", () => {
    open = !open;
    grid.style.display = open ? "grid" : "none";
    caret.textContent = open ? "▾" : "▸";
  });

  return el("div", { style: { marginTop: "var(--s-3)" } }, toggle, grid);
}

function badgeChip(b) {
  const pct = b.target > 0 ? Math.min(100, Math.round((b.current / b.target) * 100)) : 0;
  return el("div", {
    style: {
      textAlign: "center",
      padding: "var(--s-2)",
      border: `1px solid ${b.earned ? "var(--accent)" : "var(--surface-rule)"}`,
      borderRadius: "var(--r-sm)",
      background: b.earned ? "var(--surface-raised)" : "transparent",
      opacity: b.earned ? "1" : "0.6",
    },
    title: b.description,
  },
    el("div", {
      class: "subtitle",
      style: {
        color: b.earned ? "var(--accent)" : "var(--text-muted)",
        fontSize: "var(--t-xs)", lineHeight: "1.2",
      },
    }, b.name),
    el("div", {
      class: "mono",
      style: { fontSize: "var(--t-xs)", color: "var(--text-faint)", marginTop: "2px" },
    }, b.earned ? "✓ earned" : `${b.current}/${b.target}`),
  );
}
