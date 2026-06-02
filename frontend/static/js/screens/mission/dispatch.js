import { el } from "../../dom.js";
import { loadMission } from "../../flow.js";
import { navigate } from "../../router.js";
import { styleMeta } from "../../style-meta.js";

// Single-screen dispatch. With OLMo 2's tighter 200-280 char briefings,
// the old summary→brief two-step is friction we no longer need: render
// the full briefing_text directly alongside the Accept button.
// (dispatch_summary stays in the API payload — TTS, dossier previews,
// and share-card metadata still consume it.)
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

  const code = String(mission.id).slice(0, 8);
  const paragraphs = (mission.briefing_text || "").split(/\n\n+/);

  const acceptBtn = el("button", { class: "primary" }, "Accept");
  acceptBtn.addEventListener("click", () => navigate(`/mission/${mission.id}/objective`));

  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "code" }, code),
    ),
    el("div", { class: "content scrollable stack" },
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
      ...paragraphs.map((p) =>
        el("p", {
          style: { fontFamily: "var(--font-serif)", fontSize: "var(--t-base)",
                   lineHeight: "1.7", margin: 0 },
        }, p),
      ),
      mission.clue
        ? el("div", { class: "stack", style: { gap: "var(--s-2)", marginTop: "var(--s-2)" } },
            el("div", { class: "subtitle" }, "FIELD HINT"),
            el("div", { class: "code", style: { fontSize: "var(--t-sm)" } }, mission.clue),
          )
        : null,
    ),
    el("div", { class: "actions" }, acceptBtn),
  );
}
