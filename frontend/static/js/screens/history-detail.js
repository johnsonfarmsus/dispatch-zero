// Single-completion review screen — pulled from /history/:id.
// Shows the full mission card image with the same Save and Copy Share
// actions used on the post-capture Debrief screen.
import { api } from "../api.js";
import { el } from "../dom.js";
import { saveCard, copyShareText } from "../share-actions.js";

export async function historyDetail({ id }) {
  const r = await api.get(`/missions/completions/${id}`);
  if (!r.ok) {
    return el("div", { class: "screen" },
      el("div", { class: "header" },
        el("span", {}, "// dispatch zero //"),
        el("span", { class: "muted" }, "— not found"),
      ),
      el("div", { class: "content stack" },
        el("div", { class: "title" }, "Dispatch not found."),
        el("div", { class: "muted" }, "It may have been removed."),
      ),
      el("div", { class: "actions" },
        el("a", { href: "/history", "data-route": true, class: "muted",
                  style: { textAlign: "center", padding: "var(--s-2)" } },
          "← Back to Dossier"),
      ),
    );
  }

  const c = r.data;
  const date = new Date(c.completed_at);
  const dateStr = date.toLocaleDateString(undefined, {
    year: "numeric", month: "long", day: "numeric",
  });

  const saveCardBtn = el("button", {}, "Save Card");
  const copyShareBtn = el("button", {}, "Copy Share Text");
  const cardStatus = el("div", {
    class: "muted mono",
    style: { textAlign: "center", fontSize: "var(--t-xs)" },
  }, "");

  saveCardBtn.addEventListener("click",
    () => saveCard(c.id, cardStatus, saveCardBtn));
  copyShareBtn.addEventListener("click",
    () => copyShareText(c.share_token, c.place_name, cardStatus));

  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "— dispatch"),
    ),
    el("div", { class: "content stack" },
      el("img", {
        src: `/missions/completions/${c.id}/card.jpg`,
        alt: "Mission card",
        style: {
          width: "100%", maxWidth: "360px", height: "auto",
          alignSelf: "center", display: "block",
          border: "1px solid var(--surface-rule)",
        },
      }),
      el("div", { class: "stack", style: { gap: "var(--s-1)", textAlign: "center" } },
        el("div", { class: "title", style: { fontSize: "var(--t-xl)" } },
          c.place_name || "Unmarked target"),
        el("div", { class: "muted mono", style: { fontSize: "var(--t-xs)" } },
          `${(c.place_category || "").toUpperCase()} · ${dateStr}`),
      ),
    ),
    el("div", { class: "actions" },
      saveCardBtn,
      copyShareBtn,
      cardStatus,
      el("a", { href: "/history", "data-route": true, class: "muted",
                style: { textAlign: "center", padding: "var(--s-2)" } },
        "← Back to Dossier"),
    ),
  );
}
