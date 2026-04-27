import { el } from "../dom.js";
import { api } from "../api.js";
import { setUser } from "../state.js";
import { navigate } from "../router.js";

export function login() {
  const errEl = el("div", { class: "fault", hidden: true });
  const submitBtn = el("button", { type: "submit", class: "primary" }, "Authenticate");

  const callsign = el("input", { name: "callsign", autocomplete: "username", required: true });
  const password = el("input", { name: "password", type: "password", autocomplete: "current-password", required: true });

  const form = el("form", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "— authenticating"),
    ),
    el("div", { class: "content stack" },
      el("div", { class: "title" }, "Resume Field Status"),
      el("div", { class: "muted" }, "Enter your callsign and passphrase."),
      el("div", { class: "field" }, el("label", {}, "Callsign"), callsign),
      el("div", { class: "field" }, el("label", {}, "Passphrase"), password),
      errEl,
    ),
    el("div", { class: "actions" },
      submitBtn,
      el("a", {
        href: "/signup", "data-route": true, class: "muted",
        style: { textAlign: "center", padding: "var(--s-2)" },
      }, "Apply for new field status"),
    ),
  );

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errEl.hidden = true;
    submitBtn.disabled = true;
    try {
      const r = await api.post("/auth/login", {
        callsign: callsign.value,
        password: password.value,
      });
      if (r.ok) {
        setUser(r.data);
        await navigate("/", { replace: true });
        return;
      }
      throw new Error("Credentials not recognized, agent.");
    } catch (e2) {
      errEl.textContent = e2.message || "Credentials not recognized, agent.";
      errEl.hidden = false;
    } finally {
      submitBtn.disabled = false;
    }
  });

  return form;
}
