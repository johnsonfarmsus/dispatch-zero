import { el } from "../../dom.js";
import { loadMission, getLastDebrief, clearLastDebrief } from "../../flow.js";
import { navigate } from "../../router.js";

export async function debrief({ id }) {
  const mission = await loadMission(id);
  const code = String(mission.id).slice(0, 8);
  const d = getLastDebrief();

  const rateBtn = el("button", { class: "primary" }, "Rate Mission");
  const saveCardBtn = el("button", {}, "Save Card");
  const copyShareBtn = el("button", {}, "Copy Share Text");
  const cardStatus = el("div", {
    class: "muted mono",
    style: { textAlign: "center", fontSize: "var(--t-xs)" },
  }, "");
  const skipLink = el("a", {
    href: "/", "data-route": true, class: "muted",
    style: { textAlign: "center", padding: "var(--s-2)" },
  }, "Skip — Return to Base");

  if (d?.completion?.id && d?.completion?.share_token) {
    rateBtn.addEventListener("click",
      () => navigate(`/completions/${d.completion.id}/rate`));
    saveCardBtn.addEventListener("click",
      () => saveCard(d.completion.id, cardStatus, saveCardBtn));
    copyShareBtn.addEventListener("click",
      () => copyShareText(d.completion.share_token, mission.place.name, cardStatus));
  } else {
    rateBtn.disabled = true;
    saveCardBtn.disabled = true;
    copyShareBtn.disabled = true;
  }

  const stats = d
    ? el("div", { class: "stack", style: { gap: "var(--s-2)" } },
        el("div", { class: "row", style: { justifyContent: "space-between" } },
          el("span", { class: "subtitle" }, "Completions"),
          el("span", { class: "code", style: { fontSize: "var(--t-2xl)" } },
            String(d.user_completions_count)),
        ),
        el("div", { class: "row", style: { justifyContent: "space-between" } },
          el("span", { class: "subtitle" }, "This week"),
          el("span", { class: "code" }, String(d.user_missions_this_week)),
        ),
      )
    : el("div", { class: "muted" },
        "Refreshed view unavailable — return to Home for current stats.");

  const badge = mission.badge_framing
    ? el("div", { class: "stack", style: { gap: "var(--s-2)" } },
        el("div", { class: "subtitle" }, "BADGE EARNED"),
        el("div", {
          style: {
            border: "1px solid var(--accent)",
            color: "var(--accent)",
            borderRadius: "var(--r-sm)",
            padding: "var(--s-3) var(--s-4)",
            fontFamily: "var(--font-mono)",
            fontSize: "var(--t-sm)",
            textAlign: "center",
            letterSpacing: "0.05em",
          },
        }, mission.badge_framing),
      )
    : null;

  const element = el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "code" }, code),
    ),
    el("div", { class: "content stack" },
      el("div", { class: "subtitle" }, "DEBRIEF"),
      el("div", { class: "title", style: { fontSize: "var(--t-2xl)" } }, "Acknowledged."),
      el("div", {
        style: { fontFamily: "var(--font-serif)", fontSize: "var(--t-base)",
                 lineHeight: "1.6", color: "var(--text-muted)" },
      }, mission.dispatch_summary),
      el("div", { class: "divider" }),
      stats,
      badge,
    ),
    el("div", { class: "actions" }, rateBtn, saveCardBtn, copyShareBtn, cardStatus, skipLink),
  );

  return {
    element,
    cleanup: () => {
      // Clear debrief cache once user navigates away — next mission gets fresh data
    },
  };
}


// Build a sharable text + URL and put it on the clipboard. Works for any
// destination (Bluesky, Mastodon, SMS, email, etc.) — user pastes wherever.
async function copyShareText(shareToken, placeName, statusEl) {
  const url = `${window.location.origin}/c/${shareToken}`;
  const text = placeName
    ? `Dispatched to ${placeName}. ${url}`
    : `Dispatched. ${url}`;
  try {
    await navigator.clipboard.writeText(text);
    statusEl.style.color = "var(--text-muted)";
    statusEl.textContent = "Copied — paste anywhere.";
  } catch (e) {
    statusEl.style.color = "var(--danger)";
    statusEl.textContent = "Copy failed — long-press to copy: " + url;
  }
}


// Fetch the mission card and either share it (Web Share API on iOS — lets the
// user save to Photos with one tap) or download it as a fallback.
async function saveCard(completionId, statusEl, btnEl) {
  btnEl.disabled = true;
  statusEl.style.color = "var(--text-muted)";
  statusEl.textContent = "Composing card…";
  try {
    const r = await fetch(`/missions/completions/${completionId}/card.jpg`, {
      credentials: "same-origin",
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const blob = await r.blob();
    const filename = `dispatch-zero-${String(completionId).slice(0, 8)}.jpg`;

    const file = new File([blob], filename, { type: "image/jpeg" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({ files: [file] });
      statusEl.textContent = "Shared.";
    } else {
      // Download fallback
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      statusEl.textContent = "Downloaded.";
    }
  } catch (e) {
    // User-cancelled share is not an error — Web Share rejects with AbortError.
    if (e && e.name === "AbortError") {
      statusEl.textContent = "";
    } else {
      statusEl.style.color = "var(--danger)";
      statusEl.textContent = e.message || "Card unavailable.";
    }
  } finally {
    btnEl.disabled = false;
  }
}
