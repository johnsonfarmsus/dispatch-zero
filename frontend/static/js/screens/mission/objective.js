import { el } from "../../dom.js";
import {
  loadMission, startWatchingPosition, stopWatchingPosition,
  onFix, distanceM, formatDistance,
} from "../../flow.js";
import { navigate } from "../../router.js";

export async function objective({ id }) {
  const mission = await loadMission(id);
  const code = String(mission.id).slice(0, 8);
  const distEl = el("div", { class: "distance-readout" }, "Acquiring fix…");

  const beginBtn = el("button", { class: "primary" }, "Begin Transit");
  beginBtn.addEventListener("click", () => navigate(`/mission/${mission.id}/transit`));

  const element = el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "code" }, code),
    ),
    el("div", { class: "content stack" },
      el("div", { class: "subtitle" }, "OBJECTIVE"),
      el("div", { class: "title", style: { fontSize: "var(--t-2xl)" } },
        mission.place.name || "An unmarked target"),
      el("div", { class: "muted mono", style: { fontSize: "var(--t-xs)" } },
        mission.place.category.toUpperCase()),
      mission.place.description
        ? el("div", { class: "muted", style: { fontStyle: "italic" } },
            mission.place.description)
        : null,
      el("div", { class: "divider" }),
      el("div", { class: "subtitle", style: { textAlign: "center" } }, "DISTANCE TO TARGET"),
      distEl,
    ),
    el("div", { class: "actions" }, beginBtn),
  );

  startWatchingPosition();
  const off = onFix((fix) => {
    const d = distanceM(fix.lat, fix.lng, mission.place.lat, mission.place.lng);
    distEl.textContent = formatDistance(d);
  });

  return {
    element,
    cleanup: () => {
      off();
      // Don't stop watching here — Transit will keep using it
    },
  };
}
