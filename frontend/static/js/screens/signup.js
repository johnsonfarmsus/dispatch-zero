import { el } from "../dom.js";
import { api } from "../api.js";
import { setUser } from "../state.js";
import { navigate } from "../router.js";
import { STYLE_META, TAGLINES, ACCENTS } from "../style-meta.js";

export function signup() {
  const errEl = el("div", { class: "fault", hidden: true });
  const submitBtn = el("button", { type: "submit", class: "primary" }, "Submit Application");

  const callsign = el("input", {
    name: "callsign", autocomplete: "username",
    minlength: 3, maxlength: 32, pattern: "[a-zA-Z0-9_-]+", required: true,
  });
  const password = el("input", {
    name: "password", type: "password", autocomplete: "new-password",
    minlength: 8, maxlength: 128, required: true,
  });

  // Selectable org cards — same org names + taglines as the Settings style
  // picker (shared from style-meta.js) so the two screens read identically.
  let selectedStyle = "agency";  // default; the card is highlighted below
  const orderedStyles = ["pulp", "agency", "guild"];
  const cards = {};
  const nameSpans = {};

  function paintSelection() {
    for (const s of orderedStyles) {
      const btn = cards[s];
      const isSel = s === selectedStyle;
      // Highlight the selected card with THAT org's accent (not the global
      // var(--accent), which is locked to agency teal here). Unselected
      // cards fall back to the default surface rule.
      const accent = ACCENTS[s] || "var(--accent)";
      btn.style.borderColor = isSel ? accent : "var(--surface-rule)";
      // The org-name span has its own .subtitle color, so set it directly.
      nameSpans[s].style.color = isSel ? accent : "var(--text-muted)";
      // Faint tint of the org color behind the selected card.
      btn.style.background = isSel
        ? `color-mix(in srgb, ${accent} 12%, var(--surface-raised))`
        : "var(--surface-raised)";
    }
  }

  // Compact single-line org cards: org name + tagline on one row, tight
  // padding. Same names + taglines as Settings, but laid out to fit the
  // signup screen (which also carries the callsign + passphrase fields)
  // WITHOUT scrolling.
  function orgCard(s) {
    const meta = STYLE_META[s];
    const nameSpan = el("span", { class: "subtitle", style: { flex: "0 0 auto" } }, meta.org);
    const btn = el("button", {
      type: "button",
      style: {
        textAlign: "left",
        padding: "var(--s-2) var(--s-3)",
        display: "flex", alignItems: "baseline", gap: "var(--s-2)",
        flexWrap: "wrap",
      },
    },
      nameSpan,
      el("span", {
        class: "muted",
        style: { fontSize: "var(--t-xs)", lineHeight: "1.2" },
      }, TAGLINES[s] || ""),
    );
    btn.addEventListener("click", () => {
      selectedStyle = s;
      paintSelection();
    });
    cards[s] = btn;
    nameSpans[s] = nameSpan;
    return btn;
  }

  const orgButtons = orderedStyles.map(orgCard);
  paintSelection();

  const form = el("form", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "application"),
    ),
    el("div", { class: "content stack", style: { gap: "var(--s-2)" } },
      el("div", { class: "title", style: { fontSize: "var(--t-xl)" } },
        "Apply for Field Status"),
      el("div", { class: "muted", style: { fontSize: "var(--t-sm)" } },
        "No replacements are issued. Memorize what you set."),
      el("div", { class: "field" }, el("label", {}, "Callsign"), callsign),
      el("div", { class: "field" }, el("label", {}, "Passphrase"), password),
      el("div", { class: "subtitle" }, "Organization"),
      ...orgButtons,
      errEl,
    ),
    el("div", { class: "actions" },
      submitBtn,
      el("a", {
        href: "/login", "data-route": true, class: "muted",
        style: { textAlign: "center", padding: "var(--s-2)" },
      }, "Already have credentials?"),
    ),
  );

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errEl.hidden = true;
    submitBtn.disabled = true;
    try {
      const r = await api.post("/auth/signup", {
        callsign: callsign.value,
        password: password.value,
        adventure_style: selectedStyle,
      });
      if (r.ok) {
        setUser(r.data);
        await navigate("/", { replace: true });
        return;
      }
      throw new Error(r.data?.detail || "Application denied.");
    } catch (e2) {
      errEl.textContent = e2.message;
      errEl.hidden = false;
    } finally {
      submitBtn.disabled = false;
    }
  });

  return form;
}
