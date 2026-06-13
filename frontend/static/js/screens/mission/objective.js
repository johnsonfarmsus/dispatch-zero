import { el } from "../../dom.js";
import {
  loadMission, startWatchingPosition, stopWatchingPosition,
  onFix, onFixError, geoErrorMessage, distanceM, formatDistance,
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
    distEl.style.color = "";
  });
  // Surface geolocation failures instead of hanging on "Acquiring fix…".
  const offErr = onFixError((err) => {
    distEl.textContent = geoErrorMessage(err);
    distEl.style.color = "var(--danger)";
    distEl.style.fontSize = "var(--t-sm)";
  });

  return {
    element,
    cleanup: () => {
      off();
      offErr();
      // Stop the GPS watch on any exit. If the user advances to Transit,
      // its mount calls startWatchingPosition() again (idempotent), so
      // there's no coverage gap; if they back out to Home, the watch
      // stops instead of leaking a high-accuracy GPS subscription that
      // drains battery and keeps the location indicator lit. This mirrors
      // the cleanup pattern documented in report.js.
      stopWatchingPosition();
    },
  };
}
