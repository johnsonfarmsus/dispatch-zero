// Single-completion review screen. The card itself IS the page — the title /
// date / callsign / rank are already baked into the JPEG, so we don't repeat
// them as text. Two compact side-by-side buttons for Save Card + Copy Link.
import { api } from "../api.js";
import { el } from "../dom.js";
import { saveCard, copyShareText } from "../share-actions.js";

export async function historyDetail({ id }) {
  const r = await api.get(`/missions/completions/${id}`);
  if (!r.ok) {
    return el("div", { class: "screen" },
      el("div", { class: "header" },
        el("span", {}, "// dispatch zero //"),
        el("span", { class: "muted" }, "not found"),
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

  const status = el("div", {
    class: "muted mono",
    style: { textAlign: "center", fontSize: "var(--t-xs)", minHeight: "1em" },
  }, "");

  const saveBtn = el("button", { style: { flex: "1 1 0" } }, "Save Card");
  const copyBtn = el("button", { style: { flex: "1 1 0" } }, "Copy Link");
  saveBtn.addEventListener("click", () => saveCard(c.id));
  copyBtn.addEventListener("click",
    () => copyShareText(c.share_token, c.place_name, status));

  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "dispatch"),
    ),
    el("div", {
      class: "content",
      style: {
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        gap: "var(--s-3)",
      },
    },
      el("img", {
        src: `/missions/completions/${c.id}/card.jpg`,
        alt: "Mission card",
        style: {
          width: "100%", maxWidth: "420px", height: "auto",
          display: "block", border: "1px solid var(--surface-rule)",
        },
      }),
    ),
    el("div", { class: "actions" },
      el("div", { class: "row", style: { gap: "var(--s-2)" } }, saveBtn, copyBtn),
      status,
      el("a", { href: "/history", "data-route": true, class: "muted",
                style: { textAlign: "center", padding: "var(--s-2)" } },
        "← Back to Dossier"),
    ),
  );
}
