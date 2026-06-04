import { el } from "../dom.js";
import { api } from "../api.js";
import { setUser } from "../state.js";
import { navigate } from "../router.js";

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
  const styleSel = el("select", { name: "adventure_style", required: true },
    el("option", { value: "agency" }, "Agency: clinical, classified directives"),
    el("option", { value: "pulp" }, "Pulp: expeditionary, warm"),
    el("option", { value: "guild" }, "Guild: ancient, ceremonial"),
  );

  const form = el("form", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "application"),
    ),
    el("div", { class: "content stack" },
      el("div", { class: "title" }, "Apply for Field Status"),
      el("div", { class: "muted" },
        "Choose a callsign and a passphrase. The Archive does not issue replacements. Memorize what you set here.",
      ),
      el("div", { class: "field" }, el("label", {}, "Callsign"), callsign),
      el("div", { class: "field" }, el("label", {}, "Passphrase"), password),
      el("div", { class: "field" }, el("label", {}, "Operating Style"), styleSel),
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
        adventure_style: styleSel.value,
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
