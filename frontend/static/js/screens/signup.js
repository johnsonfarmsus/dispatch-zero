import { el } from "../dom.js";
import { api } from "../api.js";
import { setUser } from "../state.js";
import { navigate } from "../router.js";
import { STYLE_META, TAGLINES } from "../style-meta.js";

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

  function paintSelection() {
    for (const s of orderedStyles) {
      cards[s].className = s === selectedStyle ? "primary" : "";
    }
  }

  function orgCard(s) {
    const meta = STYLE_META[s];
    const btn = el("button", {
      type: "button",
      style: {
        textAlign: "left", padding: "var(--s-3)",
        display: "flex", flexDirection: "column", gap: "2px",
      },
    },
      el("span", { class: "subtitle" }, meta.org),
      el("span", { style: { color: "var(--text)", fontSize: "var(--t-sm)" } },
        TAGLINES[s] || ""),
    );
    btn.addEventListener("click", () => {
      selectedStyle = s;
      paintSelection();
    });
    cards[s] = btn;
    return btn;
  }

  const orgButtons = orderedStyles.map(orgCard);
  paintSelection();

  const form = el("form", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "application"),
    ),
    el("div", { class: "content stack scrollable" },
      el("div", { class: "title" }, "Apply for Field Status"),
      el("div", { class: "muted" },
        "Choose a callsign and a passphrase. The Archive does not issue replacements. Memorize what you set here.",
      ),
      el("div", { class: "field" }, el("label", {}, "Callsign"), callsign),
      el("div", { class: "field" }, el("label", {}, "Passphrase"), password),
      el("div", { class: "subtitle", style: { marginTop: "var(--s-2)" } }, "Organization"),
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
