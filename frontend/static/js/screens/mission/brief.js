import { el } from "../../dom.js";
import { loadMission } from "../../flow.js";
import { navigate } from "../../router.js";

export async function brief({ id }) {
  const mission = await loadMission(id);
  const code = String(mission.id).slice(0, 8);
  const paragraphs = mission.briefing_text.split(/\n\n+/);

  const ackBtn = el("button", { class: "primary" }, "Acknowledged");
  ackBtn.addEventListener("click", () => navigate(`/mission/${mission.id}/dispatch`));

  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "code" }, code),
    ),
    el("div", { class: "content scrollable stack" },
      el("div", { class: "subtitle" }, "FULL BRIEF"),
      el("div", { class: "title", style: { fontSize: "var(--t-2xl)" } },
        mission.place.name || "An unmarked target"),
      el("div", { class: "muted mono", style: { fontSize: "var(--t-xs)" } },
        mission.place.category.toUpperCase()),
      ...paragraphs.map((p) =>
        el("p", {
          style: { fontFamily: "var(--font-serif)", fontSize: "var(--t-base)",
                   lineHeight: "1.7", margin: 0 },
        }, p),
      ),
      mission.clue
        ? el("div", { class: "stack", style: { gap: "var(--s-2)", marginTop: "var(--s-4)" } },
            el("div", { class: "subtitle" }, "FIELD HINT"),
            el("div", { class: "code", style: { fontSize: "var(--t-sm)" } }, mission.clue),
          )
        : null,
    ),
    el("div", { class: "actions" }, ackBtn),
  );
}
