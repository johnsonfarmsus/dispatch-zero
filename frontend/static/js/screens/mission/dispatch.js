import { el } from "../../dom.js";
import { loadMission } from "../../flow.js";
import { getUser } from "../../state.js";
import { navigate } from "../../router.js";
import { styleMeta } from "../../style-meta.js";

export async function dispatch({ id }) {
  let mission;
  try {
    mission = await loadMission(id);
  } catch (e) {
    return el("div", { class: "screen" },
      el("div", { class: "header" },
        el("span", {}, "// dispatch zero //"),
        el("span", { class: "muted" }, "— error"),
      ),
      el("div", { class: "content stack" },
        el("div", { class: "title" }, "Mission not found."),
        el("div", { class: "muted" }, e.message),
      ),
      el("div", { class: "actions" },
        el("a", { href: "/", "data-route": true, class: "muted",
                  style: { textAlign: "center", padding: "var(--s-2)" } },
          "Return to Home"),
      ),
    );
  }

  const user = getUser();
  const code = String(mission.id).slice(0, 8);

  const openBrief = el("button", {}, "Open Brief");
  const acceptBtn = el("button", { class: "primary" }, "Accept");
  openBrief.addEventListener("click", () => navigate(`/mission/${mission.id}/brief`));
  acceptBtn.addEventListener("click", () => navigate(`/mission/${mission.id}/objective`));

  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "code" }, code),
    ),
    el("div", { class: "content stack" },
      el("div", { class: "handler-mark" },
        el("img", {
          src: `/static/avatars/zero-${mission.adventure_style}.png`,
          alt: styleMeta(mission.adventure_style).handler,
        }),
        el("span", {},
          `${styleMeta(mission.adventure_style).handler.toUpperCase()} // ${styleMeta(mission.adventure_style).org.toUpperCase()}`,
        ),
      ),
      el("div", { class: "subtitle" }, "DISPATCH"),
      el("div", { class: "title", style: { fontSize: "var(--t-2xl)" } },
        mission.place.name || "An unmarked target"),
      el("div", { class: "muted mono", style: { fontSize: "var(--t-xs)" } },
        mission.place.category.toUpperCase()),
      el("div", {
        style: { marginTop: "var(--s-3)", fontFamily: "var(--font-serif)",
                 fontSize: "var(--t-base)", lineHeight: "1.6" },
      }, mission.dispatch_summary),
    ),
    el("div", { class: "actions" }, openBrief, acceptBtn),
  );
}
