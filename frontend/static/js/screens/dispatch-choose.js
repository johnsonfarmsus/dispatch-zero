// Dispatch choice screen — shows the 3 nearby place options from the last
// "Request Dispatch" and lets the user pick one. The briefing is generated
// only on accept (POST /missions/candidates/accept), so this screen is fast.
//
// Each card: place name, category, distance + compass bearing, and a short
// preview. Tapping a card generates that mission and moves into the dispatch
// (briefing) screen. A back-to-home link discards the slate.

import { el } from "../dom.js";
import { api } from "../api.js";
import { getCandidates, clearMissionCache } from "../flow.js";
import { navigate } from "../router.js";
import { getUser } from "../state.js";
import { formatDistance } from "../flow.js";

function _categoryLabel(slug) {
  return (slug || "").replace(/_/g, " ").toUpperCase();
}

export function dispatchChoose() {
  const candidates = getCandidates();
  // If there's no slate (deep link, refresh — the list lives in module
  // memory), send the user back home to request one.
  if (!candidates || candidates.length === 0) {
    navigate("/", { replace: true });
    return el("div");
  }

  const user = getUser();
  const style = user?.adventure_style || "agency";

  const status = el("div", {
    class: "muted mono",
    style: { fontSize: "var(--t-xs)", textAlign: "center", minHeight: "1em" },
  }, "");

  const list = el("div", { class: "stack", style: { gap: "var(--s-3)" } },
    ...candidates.map((c) => candidateCard(c, status)),
  );

  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "choose"),
    ),
    el("div", { class: "content stack scrollable", style: { gap: "var(--s-2)" } },
      el("div", { class: "subtitle" }, "SELECT YOUR DISPATCH"),
      el("div", { class: "muted", style: { fontSize: "var(--t-sm)", marginBottom: "var(--s-2)" } },
        "Three targets are in range, agent. Pick one."),
      status,
      list,
    ),
    el("div", { class: "actions" },
      el("a", {
        href: "/", "data-route": true, class: "muted",
        style: { textAlign: "center", padding: "var(--s-2)" },
      }, "← Back to Home"),
    ),
  );
}

function candidateCard(c, status) {
  const card = el("button", {
    style: {
      width: "100%", textAlign: "left", display: "flex",
      flexDirection: "column", gap: "var(--s-1)",
      padding: "var(--s-3)",
      border: "1px solid var(--surface-rule)",
      borderRadius: "var(--r-md)",
      background: "var(--surface-raised)",
    },
  },
    el("div", { class: "row", style: { justifyContent: "space-between", alignItems: "baseline", gap: "var(--s-2)" } },
      el("span", {
        style: {
          fontSize: "var(--t-lg)", fontWeight: "600", color: "var(--text)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        },
      }, c.place_name || "Unmarked target"),
      el("span", {
        class: "code", style: { fontSize: "var(--t-sm)", flex: "0 0 auto", color: "var(--accent)" },
      }, `${formatDistance(c.distance_m)} ${c.bearing_compass}`),
    ),
    el("div", { class: "muted mono", style: { fontSize: "var(--t-xs)" } },
      _categoryLabel(c.place_category)),
    c.preview
      ? el("div", {
          style: {
            fontSize: "var(--t-sm)", lineHeight: "1.4", color: "var(--text-muted)",
            marginTop: "2px",
          },
        }, c.preview)
      : null,
  );

  card.addEventListener("click", async () => {
    // Disable all sibling cards while generating.
    card.disabled = true;
    status.style.color = "var(--text-muted)";
    status.textContent = "Generating your briefing…";
    try {
      const r = await api.post("/missions/candidates/accept", {
        place_id: c.place_id,
      });
      if (r.ok) {
        clearMissionCache();
        await navigate(`/mission/${r.data.id}/dispatch`);
        return;
      }
      throw new Error(r.data?.detail || "Dispatch line is unreliable.");
    } catch (e) {
      status.style.color = "var(--danger)";
      status.textContent = e.status === 503
        ? "The dispatch line is unreliable, agent. Try again."
        : (e.message || "Could not generate that dispatch.");
      card.disabled = false;
    }
  });

  return card;
}
