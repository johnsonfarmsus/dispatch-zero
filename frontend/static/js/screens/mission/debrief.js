import { el } from "../../dom.js";
import { loadMission, getLastDebrief, clearLastDebrief } from "../../flow.js";
import { navigate } from "../../router.js";
import { saveCard, copyShareText } from "../../share-actions.js";

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
