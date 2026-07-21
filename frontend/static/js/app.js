import { el } from "./dom.js";
import { api } from "./api.js";
import { setUser, clearUser, getUser } from "./state.js";
import { defineRoute, defineNotFound, init, navigate } from "./router.js";
import { splash } from "./screens/splash.js";
import { signup } from "./screens/signup.js";
import { login } from "./screens/login.js";
import { home } from "./screens/home.js";
import { stylePicker } from "./screens/style-picker.js";
import { dispatch as missionDispatch } from "./screens/mission/dispatch.js";
import { dispatchChoose } from "./screens/dispatch-choose.js";
import { objective as missionObjective } from "./screens/mission/objective.js";
import { transit as missionTransit } from "./screens/mission/transit.js";
import { missionMap } from "./screens/mission/map.js";
import { capture as missionCapture } from "./screens/mission/capture.js";
import { debrief as missionDebrief } from "./screens/mission/debrief.js";
import { rate as missionRate } from "./screens/mission/rate.js";
import { history } from "./screens/history.js";
import { historyDetail } from "./screens/history-detail.js";
import { report } from "./screens/report.js";
import { submissionDetail } from "./screens/submission-detail.js";
import { securityProtocols } from "./screens/security-protocols.js";
import { adminQueue } from "./screens/admin/queue.js";

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
  defineRoute("/dispatch/choose", () => dispatchChoose());
  defineRoute("/mission/:id/dispatch", (p) => missionDispatch(p));
  defineRoute("/mission/:id/objective", (p) => missionObjective(p));
  defineRoute("/mission/:id/transit", (p) => missionTransit(p));
  defineRoute("/mission/:id/map", (p) => missionMap(p));
  defineRoute("/mission/:id/capture", (p) => missionCapture(p));
  defineRoute("/mission/:id/debrief", (p) => missionDebrief(p));
  defineRoute("/completions/:id/rate", (p) => missionRate(p));
  defineRoute("/history", () => history());
  defineRoute("/history/:id", (p) => historyDetail(p));
  defineRoute("/report", () => report());
  defineRoute("/submission/:id/debrief", (p) => submissionDetail(p));
  defineRoute("/submission/:id", (p) => submissionDetail(p));
  defineRoute("/security", () => securityProtocols());
  defineRoute("/admin/queue", () => adminQueue());
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
    el("div", { class: "actions" },
      goSignup,
      goLogin,
      el("a", {
        href: "/security", "data-route": true, class: "muted mono",
        style: { textAlign: "center", fontSize: "var(--t-xs)",
                 letterSpacing: "0.05em", padding: "var(--s-2)" },
      }, "// SECURITY PROTOCOLS //"),
    ),
  );
}
