import { el } from "../../dom.js";
import { api } from "../../api.js";
import {
  loadMission, getFreshFix, setLastDebrief, stopWatchingPosition,
} from "../../flow.js";
import { navigate } from "../../router.js";

export async function capture({ id }) {
  const mission = await loadMission(id);
  const code = String(mission.id).slice(0, 8);

  const fileInput = el("input", {
    type: "file",
    accept: "image/*",
    capture: "environment",
  });

  const captureLabel = el("label", { class: "capture-target" },
    el("svg", {
      width: "80", height: "80", viewBox: "0 0 24 24",
      style: { color: "var(--accent)" },
    }),
    el("span", {
      class: "subtitle",
      style: { fontSize: "var(--t-base)", color: "var(--accent)" },
    }, "TAP TO CAPTURE"),
    fileInput,
  );

  // Camera icon SVG (built without innerHTML)
  const svg = captureLabel.querySelector("svg");
  const ns = "http://www.w3.org/2000/svg";
  const path1 = document.createElementNS(ns, "path");
  path1.setAttribute("d", "M9 3 L7 5 L4 5 A1 1 0 0 0 3 6 L3 18 A1 1 0 0 0 4 19 L20 19 A1 1 0 0 0 21 18 L21 6 A1 1 0 0 0 20 5 L17 5 L15 3 Z");
  path1.setAttribute("fill", "none");
  path1.setAttribute("stroke", "currentColor");
  path1.setAttribute("stroke-width", "1.5");
  svg.appendChild(path1);
  const circle = document.createElementNS(ns, "circle");
  circle.setAttribute("cx", "12"); circle.setAttribute("cy", "13"); circle.setAttribute("r", "4");
  circle.setAttribute("fill", "none");
  circle.setAttribute("stroke", "currentColor");
  circle.setAttribute("stroke-width", "1.5");
  svg.appendChild(circle);

  const errEl = el("div", { class: "fault", hidden: true });
  const cancelLink = el("a", {
    href: `/mission/${mission.id}/transit`, "data-route": true, class: "muted",
    style: { textAlign: "center", padding: "var(--s-2)", fontSize: "var(--t-xs)" },
  }, "Cancel");

  const element = el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "code" }, code),
    ),
    el("div", { class: "content stack", style: { justifyContent: "center" } },
      el("div", { class: "subtitle" }, "CAPTURE"),
      el("div", { class: "title", style: { fontSize: "var(--t-xl)" } },
        mission.place.name || "Target"),
      captureLabel,
      el("div", { class: "muted mono", style: { fontSize: "var(--t-xs)", textAlign: "center" } },
        "Photo saves to your camera roll automatically."),
      errEl,
    ),
    el("div", { class: "actions" }, cancelLink),
  );

  fileInput.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    errEl.hidden = true;
    captureLabel.classList.add("transmitting");
    captureLabel.querySelector(".subtitle").textContent = "TRANSMITTING PROOF…";

    try {
      const fix = await getFreshFix({ maxAgeMs: 10000 });
      const fd = new FormData();
      fd.append("photo", file);
      fd.append("lat", String(fix.lat));
      fd.append("lng", String(fix.lng));
      fd.append("accuracy_m", String(fix.accuracy_m ?? ""));

      const r = await api.postForm(`/missions/${mission.id}/capture`, fd);
      if (r.ok) {
        setLastDebrief(r.data);
        stopWatchingPosition();
        await navigate(`/mission/${mission.id}/debrief`, { replace: true });
        return;
      }
      throw new Error(r.data?.detail || "Transmission failed.");
    } catch (e2) {
      errEl.textContent = e2.status === 422
        ? "The proof is not yet sufficient, agent. Try again."
        : (e2.message || "Transmission failed.");
      errEl.hidden = false;
      captureLabel.classList.remove("transmitting");
      captureLabel.querySelector(".subtitle").textContent = "TAP TO CAPTURE";
      // Reset input so the user can pick the same/different file again
      fileInput.value = "";
    }
  });

  return { element, cleanup: () => {} };
}
