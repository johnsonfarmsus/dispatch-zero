import { el } from "./dom.js";
import { api } from "./api.js";
import { setUser, clearUser, getUser } from "./state.js";
import { defineRoute, defineNotFound, init, navigate } from "./router.js";
import { splash } from "./screens/splash.js";
import { signup } from "./screens/signup.js";
import { login } from "./screens/login.js";
import { home } from "./screens/home.js";
import { stylePicker } from "./screens/style-picker.js";

const root = document.getElementById("app");

// Initial paint: splash, while we check auth state.
root.replaceChildren(splash());

// Register service worker (best-effort)
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}

bootstrap();

async function bootstrap() {
  try {
    const r = await api.get("/auth/me");
    if (r.ok) {
      setUser(r.data);
    } else {
      clearUser();
    }
  } catch {
    clearUser();
  }

  defineRoute("/", () => (getUser() ? home() : anonLanding()));
  defineRoute("/signup", () => signup());
  defineRoute("/login", () => login());
  defineRoute("/style", () => stylePicker());
  defineNotFound(() => (getUser() ? home() : anonLanding()));

  init(root);
}

function anonLanding() {
  const goSignup = el("button", { class: "primary" }, "Apply for Field Status");
  const goLogin = el("button", {}, "I have credentials");

  goSignup.addEventListener("click", () => navigate("/signup"));
  goLogin.addEventListener("click", () => navigate("/login"));

  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "— uncredentialed"),
    ),
    el("div", { class: "content stack", style: { justifyContent: "center" } },
      el("div", { class: "title" }, "No active credentials."),
      el("div", { class: "muted" }, "Sign up to request your first dispatch, agent."),
    ),
    el("div", { class: "actions" }, goSignup, goLogin),
  );
}
