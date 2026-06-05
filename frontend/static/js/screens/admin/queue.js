// Admin review queue — UNIFIED. Pending user-submissions + completion-
// driven OSM publish candidates, all in one FIFO-ish list. Each card carries
// a source badge ("Community / Wikipedia / GNIS / Other") so the reviewer
// knows where it came from.
//
// Per-kind action sets:
//   kind="submission" — Approve / Submit to OSM / Return
//   kind="completion_candidate" — Submit to OSM / Skip
//
// Submit to OSM works the same way for both. For ambiguous categories
// (historic, infrastructure) the subtype picker reveals before publish.
// Already-published places hide the Submit-to-OSM button server-side.

import { el } from "../../dom.js";
import { api } from "../../api.js";
import { getUser } from "../../state.js";
import { navigate } from "../../router.js";

const _SOURCE_STYLE = {
  community:  { label: "Community",  color: "#a472d6" },  // guild purple
  wikipedia:  { label: "Wikipedia",  color: "#4ec5d6" },  // agency teal
  gnis:       { label: "GNIS",       color: "#d68a3c" },  // pulp orange
  other:      { label: "Other",      color: "#857d72" },  // muted
};

function _categoryLabel(slug) {
  if (!slug) return "uncategorized";
  return slug.replace(/_/g, " ");
}

function _formatTimestamp(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium", timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

export function adminQueue() {
  const user = getUser();
  if (!user || !user.is_admin) {
    navigate("/", { replace: true });
    return el("div");
  }

  let osmStatus = null;

  const banner = el("div", {}, "");
  const list = el("div", { class: "stack", style: { gap: "var(--s-4)" } });
  const status = el("div", {
    class: "muted mono",
    style: { fontSize: "var(--t-sm)", textAlign: "center" },
  }, "Loading queue…");

  async function refreshOsmStatus() {
    try {
      const r = await api.get("/admin/osm/status");
      osmStatus = r.ok ? r.data : null;
    } catch {
      osmStatus = null;
    }
    banner.replaceChildren(renderBanner(osmStatus));
  }

  async function refresh() {
    list.replaceChildren();
    status.style.color = "var(--text-muted)";
    status.textContent = "Loading queue…";
    await refreshOsmStatus();
    try {
      const r = await api.get("/admin/queue");
      if (!r.ok) {
        status.style.color = "var(--danger)";
        status.textContent = "Could not load queue.";
        return;
      }
      const rows = r.data || [];
      if (rows.length === 0) {
        status.textContent = "Queue is clean. No pending items.";
        return;
      }
      // Itemize by kind so the reviewer can scan the breakdown at a glance.
      const subs = rows.filter((r) => r.kind === "submission").length;
      const cands = rows.filter((r) => r.kind === "completion_candidate").length;
      const parts = [];
      if (subs) parts.push(`${subs} submission${subs === 1 ? "" : "s"}`);
      if (cands) parts.push(`${cands} candidate${cands === 1 ? "" : "s"}`);
      status.textContent = parts.join(" · ");
      rows.forEach((item) =>
        list.appendChild(renderCard(item, () => osmStatus, refresh))
      );
    } catch (err) {
      status.style.color = "var(--danger)";
      status.textContent = err.message || "Queue failed to load.";
    }
  }

  refresh();

  const url = new URL(window.location.href);
  if (url.searchParams.get("osm") === "connected") {
    status.textContent = "OSM connected.";
    status.style.color = "var(--accent)";
    url.searchParams.delete("osm");
    window.history.replaceState({}, "", url.pathname + url.search);
  }

  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "review queue"),
    ),
    el("div", { class: "content stack scrollable", style: { gap: "var(--s-3)" } },
      banner,
      status,
      list,
    ),
    el("div", { class: "actions" },
      el("a", {
        href: "/style", "data-route": true, class: "muted",
        style: { textAlign: "center", padding: "var(--s-2)" },
      }, "Back to Settings"),
    ),
  );
}

function renderBanner(s) {
  if (!s) {
    return el("div", {
      class: "muted mono",
      style: {
        fontSize: "var(--t-xs)", textAlign: "center",
        padding: "var(--s-2)", border: "1px dashed var(--surface-rule)",
        borderRadius: "var(--r-sm)",
      },
    }, "OSM status unavailable.");
  }
  if (!s.server_configured) {
    return el("div", {
      class: "muted mono",
      style: {
        fontSize: "var(--t-xs)", textAlign: "center",
        padding: "var(--s-2)", border: "1px dashed var(--surface-rule)",
        borderRadius: "var(--r-sm)",
      },
    }, "OSM credentials not configured on this server.");
  }
  if (!s.connected) {
    const connectLink = el("a", {
      href: "/admin/osm/connect",
      style: { color: "var(--accent)", textDecoration: "none" },
    }, "Connect OSM →");
    return el("div", {
      class: "row mono",
      style: {
        justifyContent: "space-between", alignItems: "center",
        fontSize: "var(--t-xs)",
        padding: "var(--s-2) var(--s-3)",
        border: "1px solid var(--surface-rule)",
        borderRadius: "var(--r-sm)",
      },
    },
      el("span", { class: "muted" }, "OSM: not connected"),
      connectLink,
    );
  }
  const capText = s.dry_run
    ? `${s.username} · dry-run (cap ${s.daily_cap}/day)`
    : `${s.username} · ${s.today_count}/${s.daily_cap} today`;
  const disconnectBtn = el("a", {
    href: "#",
    style: { color: "var(--text-muted)", textDecoration: "none", fontSize: "var(--t-xs)" },
  }, "disconnect");
  disconnectBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    if (!confirm("Disconnect OSM? You'll need to reconnect before publishing again.")) {
      return;
    }
    try {
      await api.post("/admin/osm/disconnect");
      window.location.reload();
    } catch (err) {
      alert(err.message || "Disconnect failed.");
    }
  });
  return el("div", {
    class: "row mono",
    style: {
      justifyContent: "space-between", alignItems: "center",
      fontSize: "var(--t-xs)",
      padding: "var(--s-2) var(--s-3)",
      border: "1px solid var(--accent-dim)",
      borderRadius: "var(--r-sm)",
      color: "var(--accent)",
    },
  },
    el("span", {}, `OSM: ${capText}`),
    disconnectBtn,
  );
}

function renderPreflight(pf) {
  // Three-state rendering. Color cues match the convention used
  // elsewhere: muted for pending, accent for clear, danger-ish for
  // matches (not "bad", just "look here before approving").
  if (pf.state === "pending") {
    return el("div", {
      class: "mono",
      style: {
        fontSize: "var(--t-xs)", color: "var(--text-muted)",
        padding: "var(--s-1) 0",
      },
    }, "OSM pre-flight: pending…");
  }
  if (pf.state === "clear") {
    return el("div", {
      class: "mono",
      style: {
        fontSize: "var(--t-xs)", color: "var(--success)",
        padding: "var(--s-1) 0",
      },
    }, "OSM pre-flight: clear (no nearby matches within 50m)");
  }
  // matches
  const matches = pf.matches || [];
  const head = el("div", {
    class: "mono",
    style: {
      fontSize: "var(--t-xs)", color: "var(--danger)",
      padding: "var(--s-1) 0",
    },
  }, `OSM pre-flight: ${matches.length} nearby match${matches.length === 1 ? "" : "es"} — verify before publishing`);
  const list = el("ul", {
    style: {
      margin: "0", paddingLeft: "var(--s-4)",
      fontSize: "var(--t-xs)", lineHeight: "1.4",
    },
  },
    ...matches.slice(0, 5).map((m) => el("li", {},
      el("a", {
        href: m.osm_url, target: "_blank", rel: "noopener",
        style: { color: "var(--accent)" },
      }, m.name || "(unnamed)"),
      el("span", { class: "muted" }, ` · ${m.distance_m}m`),
      m.tags_summary
        ? el("span", { class: "muted", style: { fontSize: "var(--t-xs)" } },
            ` · ${m.tags_summary}`)
        : null,
    )),
    matches.length > 5
      ? el("li", { class: "muted" }, `…and ${matches.length - 5} more`)
      : null,
  );
  return el("div", {}, head, list);
}


function renderCard(item, getOsmStatus, onChange) {
  const isSubmission = item.kind === "submission";
  const isCandidate = item.kind === "completion_candidate";

  const cardStatus = el("div", {
    class: "mono",
    style: {
      fontSize: "var(--t-xs)",
      color: "var(--text-muted)",
      minHeight: "1em",
      textAlign: "center",
    },
  }, "");

  // Action buttons differ per kind.
  const approveBtn = isSubmission
    ? el("button", { class: "primary" }, "Approve")
    : null;
  const returnBtn = isSubmission ? el("button", {}, "Return") : null;
  const skipBtn = isCandidate ? el("button", {}, "Skip") : null;

  // Submit to OSM — shown for either kind when publishable + not already on OSM.
  const alreadyPublished = item.osm_already_published_node_id != null;
  const osmBtn = (item.osm_publishable && !alreadyPublished)
    ? el("button", { style: { borderColor: "var(--accent)", color: "var(--accent)" } },
        "Submit to OSM")
    : null;

  // Return-with-note (submissions only).
  const noteInput = isSubmission
    ? el("textarea", {
        maxlength: "200", rows: "2",
        placeholder: "Optional note for the submitter (why returned).",
        style: { resize: "vertical", display: "none" },
      })
    : null;
  const confirmReturnBtn = isSubmission
    ? el("button", {
        style: { display: "none", borderColor: "var(--danger)", color: "var(--danger)" },
      }, "Confirm Return")
    : null;

  // Subtype picker (both kinds, ambiguous categories only).
  const picker = item.osm_picker;
  const pickerSelect = picker
    ? el("select", { style: { display: "none" } },
        el("option", { value: "" }, "Pick a subtype…"),
        ...picker.map((p) => el("option", { value: p.value }, p.label)),
      )
    : null;
  const confirmOsmBtn = picker
    ? el("button", {
        style: { display: "none", borderColor: "var(--accent)", color: "var(--accent)" },
      }, "Confirm + OSM")
    : null;

  function setAllDisabled(v) {
    if (approveBtn) approveBtn.disabled = v;
    if (returnBtn) returnBtn.disabled = v;
    if (skipBtn) skipBtn.disabled = v;
    if (osmBtn) osmBtn.disabled = v;
    if (confirmReturnBtn) confirmReturnBtn.disabled = v;
    if (confirmOsmBtn) confirmOsmBtn.disabled = v;
  }

  if (approveBtn) {
    approveBtn.addEventListener("click", async () => {
      setAllDisabled(true);
      cardStatus.style.color = "var(--text-muted)";
      cardStatus.textContent = "Approving…";
      try {
        await api.post(`/admin/submissions/${item.id}/approve`);
        await onChange();
      } catch (err) {
        cardStatus.style.color = "var(--danger)";
        cardStatus.textContent = err.message || "Approve failed.";
        setAllDisabled(false);
      }
    });
  }

  if (returnBtn) {
    returnBtn.addEventListener("click", () => {
      noteInput.style.display = "block";
      confirmReturnBtn.style.display = "block";
      returnBtn.style.display = "none";
      if (osmBtn) osmBtn.style.display = "none";
      noteInput.focus();
      confirmReturnBtn.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  if (confirmReturnBtn) {
    confirmReturnBtn.addEventListener("click", async () => {
      setAllDisabled(true);
      cardStatus.style.color = "var(--text-muted)";
      cardStatus.textContent = "Returning…";
      try {
        const fd = new FormData();
        if (noteInput.value.trim()) {
          fd.append("note", noteInput.value.trim());
        }
        await api.postForm(`/admin/submissions/${item.id}/return`, fd);
        await onChange();
      } catch (err) {
        cardStatus.style.color = "var(--danger)";
        cardStatus.textContent = err.message || "Return failed.";
        setAllDisabled(false);
      }
    });
  }

  if (skipBtn) {
    skipBtn.addEventListener("click", async () => {
      if (!confirm("Skip this candidate? It won't reappear in your queue.")) {
        return;
      }
      setAllDisabled(true);
      cardStatus.style.color = "var(--text-muted)";
      cardStatus.textContent = "Skipping…";
      try {
        await api.post(`/admin/places/${item.place_id}/skip-osm`);
        await onChange();
      } catch (err) {
        cardStatus.style.color = "var(--danger)";
        cardStatus.textContent = err.message || "Skip failed.";
        setAllDisabled(false);
      }
    });
  }

  async function publishOsm(pickerChoice) {
    setAllDisabled(true);
    cardStatus.style.color = "var(--text-muted)";
    cardStatus.textContent = isSubmission
      ? "Approving + publishing to OSM…"
      : "Publishing to OSM…";
    try {
      const fd = new FormData();
      if (pickerChoice) fd.append("picker_choice", pickerChoice);
      const path = isSubmission
        ? `/admin/submissions/${item.id}/approve-and-publish-osm`
        : `/admin/places/${item.place_id}/publish-osm`;
      const r = await api.postForm(path, fd);
      if (r.data?.osm_dry_run) {
        cardStatus.style.color = "var(--accent)";
        cardStatus.textContent = "Published (dry-run logged).";
      } else if (r.data?.osm_node_id) {
        cardStatus.style.color = "var(--accent)";
        cardStatus.textContent = `Published as OSM node ${r.data.osm_node_id}.`;
      } else {
        cardStatus.style.color = "var(--accent)";
        cardStatus.textContent = "Published.";
      }
      setTimeout(() => onChange(), 600);
    } catch (err) {
      cardStatus.style.color = "var(--danger)";
      cardStatus.textContent = err.message || "OSM publish failed.";
      setAllDisabled(false);
    }
  }

  if (osmBtn) {
    osmBtn.addEventListener("click", async () => {
      const s = getOsmStatus();
      if (!s || !s.connected) {
        cardStatus.style.color = "var(--danger)";
        cardStatus.textContent = "Connect OSM first (banner above).";
        return;
      }
      if (!s.dry_run && s.today_count >= s.daily_cap) {
        cardStatus.style.color = "var(--danger)";
        cardStatus.textContent =
          `Daily OSM cap reached (${s.today_count}/${s.daily_cap}).`;
        return;
      }
      if (picker) {
        pickerSelect.style.display = "block";
        confirmOsmBtn.style.display = "block";
        osmBtn.style.display = "none";
        pickerSelect.focus();
        confirmOsmBtn.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      }
      await publishOsm(null);
    });
  }

  if (confirmOsmBtn) {
    confirmOsmBtn.addEventListener("click", async () => {
      const choice = pickerSelect.value;
      if (!choice) {
        cardStatus.style.color = "var(--danger)";
        cardStatus.textContent = "Pick a subtype first.";
        return;
      }
      await publishOsm(choice);
    });
  }

  // ----- Card layout -----
  const sourceStyle = _SOURCE_STYLE[item.source] || _SOURCE_STYLE.other;
  const sourceBadge = el("span", {
    class: "mono",
    style: {
      fontSize: "var(--t-xs)",
      padding: "1px var(--s-2)",
      border: `1px solid ${sourceStyle.color}`,
      color: sourceStyle.color,
      borderRadius: "var(--r-sm)",
      textTransform: "uppercase",
      letterSpacing: "0.06em",
    },
  }, sourceStyle.label);

  return el("div", {
    style: {
      border: "1px solid var(--surface-rule)",
      borderRadius: "var(--r-md)",
      padding: "var(--s-3)",
      display: "flex",
      flexDirection: "column",
      gap: "var(--s-2)",
      background: "var(--surface-raised)",
    },
  },
    el("img", {
      src: item.photo_url,
      alt: item.name,
      style: {
        width: "100%", maxHeight: "300px", objectFit: "cover",
        borderRadius: "var(--r-sm)", display: "block",
      },
    }),
    el("div", { class: "stack", style: { gap: "2px" } },
      el("div", { class: "row", style: { gap: "var(--s-2)", alignItems: "center" } },
        sourceBadge,
        el("div", { class: "subtitle", style: { color: "var(--text)" } },
          item.name || "(no name)"),
      ),
      el("div", { class: "muted mono", style: { fontSize: "var(--t-xs)" } },
        `${_categoryLabel(item.category)} · ${item.actor_callsign} (${item.actor_style})` +
          (isCandidate ? " completed" : " submitted")),
    ),
    item.description
      ? el("p", {
          style: {
            margin: 0, fontSize: "var(--t-sm)", lineHeight: "1.4",
            color: "var(--text)",
          },
        }, item.description)
      : (item.external_link ? null : el("p", {
          style: {
            margin: 0, fontSize: "var(--t-sm)", color: "var(--text-faint)",
            fontStyle: "italic",
          },
        }, "(no description)")),
    item.external_link
      ? el("a", {
          href: item.external_link, target: "_blank", rel: "noopener",
          style: {
            display: "block",
            fontSize: "var(--t-sm)",
            color: "var(--accent)",
            textOverflow: "ellipsis",
            overflow: "hidden",
            whiteSpace: "nowrap",
          },
        }, item.external_link)
      : null,
    el("div", { class: "row", style: { justifyContent: "space-between", alignItems: "baseline" } },
      el("a", {
        href: item.maps_url, target: "_blank", rel: "noopener",
        class: "mono",
        style: { fontSize: "var(--t-xs)" },
      }, `${item.lat.toFixed(5)}, ${item.lng.toFixed(5)} ↗`),
      el("span", {
        class: "muted mono",
        style: { fontSize: "var(--t-xs)" },
      }, _formatTimestamp(item.occurred_at)),
    ),
    // OSM pre-flight strip — advisory only. Three visual states:
    //   pending  — Overpass round-trip hasn't completed yet
    //   clear    — ran, no nearby matches at this category
    //   matches  — ran, list the nearby OSM nodes for cross-check
    // The clickable OSM map link above is the ground truth; this just
    // gives a heads-up that the area is dense.
    item.osm_preflight ? renderPreflight(item.osm_preflight) : null,
    pickerSelect,
    noteInput,
    cardStatus,
    el("div", { class: "row", style: { gap: "var(--s-2)", flexWrap: "wrap" } },
      approveBtn,
      osmBtn,
      returnBtn,
      skipBtn,
      confirmReturnBtn,
      confirmOsmBtn,
    ),
  );
}
