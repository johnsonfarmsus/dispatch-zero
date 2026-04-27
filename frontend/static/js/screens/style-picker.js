import { el } from "../dom.js";
import { api } from "../api.js";
import { getUser, setUser } from "../state.js";
import { navigate } from "../router.js";

const META = {
  pulp:   { top: "PULP // THE ARCHIVE",   bottom: "Warm, expeditionary. Brass-amber palette." },
  agency: { top: "AGENCY // CLASSIFIED",  bottom: "Clipped, classified. Cold cyan, surveillance feel." },
  guild:  { top: "GUILD // CEREMONIAL",   bottom: "Ancient, ceremonial. Hooded, deep purple register." },
};

export function stylePicker() {
  const current = getUser()?.adventure_style || "agency";
  const errEl = el("div", { class: "fault", hidden: true });

  function styleOption(s) {
    const isCurrent = s === current;
    const btn = el("button", {
      class: isCurrent ? "primary" : "",
      style: {
        textAlign: "left",
        padding: "var(--s-4)",
        display: "flex",
        flexDirection: "column",
        gap: "var(--s-1)",
      },
    },
      el("span", { class: "subtitle" }, META[s].top),
      el("span", { style: { color: "var(--text)" } }, META[s].bottom),
    );
    btn.addEventListener("click", async () => {
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
      el("span", { class: "muted" }, "— style"),
    ),
    el("div", { class: "content stack" },
      el("div", { class: "title" }, "Operating Style"),
      el("div", { class: "muted" },
        "Style controls Zero's voice, tone, and visual register. Switching does not affect completion history.",
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
