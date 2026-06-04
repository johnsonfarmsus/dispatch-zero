import { el } from "../../dom.js";
import {
  loadMission, startWatchingPosition, stopWatchingPosition,
  onFix, getLastFix, distanceM, bearingDeg, bearingCompassLabel, formatDistance,
} from "../../flow.js";
import { navigate } from "../../router.js";

const RADIUS_M = 80;  // mirrors server's gps_verification_radius_m

function makeArrowSvg() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "compass-arrow");
  svg.setAttribute("viewBox", "0 0 100 100");
  svg.style.color = "var(--accent)";
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", "M50 8 L62 70 L50 60 L38 70 Z");
  path.setAttribute("fill", "currentColor");
  svg.appendChild(path);
  return svg;
}

export async function transit({ id }) {
  const mission = await loadMission(id);
  const code = String(mission.id).slice(0, 8);

  const arrow = makeArrowSvg();
  const compassWrap = el("div", { class: "compass" }, arrow);

  const distEl = el("div", { class: "distance-readout" }, "...");
  const bearingEl = el("div", { class: "bearing-readout" }, "ACQUIRING FIX");

  const captureBtn = el("button", { class: "primary", disabled: true },
    "Closer, agent…");
  captureBtn.addEventListener("click", () => navigate(`/mission/${mission.id}/capture`));

  const standDownLink = el("a", {
    href: "/", "data-route": true, class: "muted",
    style: { textAlign: "center", padding: "var(--s-2)", fontSize: "var(--t-xs)" },
  }, "Stand down");

  let needsCompassPermission = false;
  if (typeof DeviceOrientationEvent !== "undefined" &&
      typeof DeviceOrientationEvent.requestPermission === "function") {
    needsCompassPermission = true;
  }

  let deviceHeading = 0;
  let bearingToTarget = null;

  function updateArrow() {
    if (bearingToTarget == null) return;
    const rot = ((bearingToTarget - deviceHeading) + 360) % 360;
    arrow.style.transform = `rotate(${rot}deg)`;
  }

  function orientationHandler(event) {
    let heading;
    if (typeof event.webkitCompassHeading === "number") {
      heading = event.webkitCompassHeading;
    } else if (typeof event.alpha === "number") {
      heading = (360 - event.alpha) % 360;
    } else {
      return;
    }
    deviceHeading = heading;
    updateArrow();
  }

  function attachOrientationListener() {
    window.addEventListener("deviceorientation", orientationHandler);
  }

  if (needsCompassPermission) {
    const enableOverlay = el("button", {
      style: {
        position: "absolute", inset: "0",
        background: "rgba(14, 12, 10, 0.85)",
        border: "1px solid var(--accent)",
        borderRadius: "50%",
        color: "var(--accent)",
        fontFamily: "var(--font-mono)",
        fontSize: "var(--t-xs)",
        textTransform: "uppercase",
        letterSpacing: "0.1em",
      },
    }, "Enable compass");
    enableOverlay.addEventListener("click", async () => {
      try {
        const perm = await DeviceOrientationEvent.requestPermission();
        if (perm === "granted") {
          attachOrientationListener();
          enableOverlay.remove();
        }
      } catch {
        enableOverlay.remove();
      }
    });
    compassWrap.style.position = "relative";
    compassWrap.appendChild(enableOverlay);
  } else {
    attachOrientationListener();
  }

  startWatchingPosition();

  function applyFix(fix) {
    const d = distanceM(fix.lat, fix.lng, mission.place.lat, mission.place.lng);
    const b = bearingDeg(fix.lat, fix.lng, mission.place.lat, mission.place.lng);
    bearingToTarget = b;
    distEl.textContent = formatDistance(d);
    bearingEl.textContent = `BEARING ${bearingCompassLabel(b)} ${Math.round(b)}°`;
    updateArrow();

    if (d <= RADIUS_M) {
      captureBtn.disabled = false;
      captureBtn.textContent = "Capture";
    } else {
      captureBtn.disabled = true;
      captureBtn.textContent = `Closer, agent. ${formatDistance(d - RADIUS_M)} to range`;
    }
  }

  const initial = getLastFix();
  if (initial) applyFix(initial);
  const off = onFix(applyFix);

  const element = el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "code" }, code),
    ),
    el("div", { class: "content stack", style: { justifyContent: "center", alignItems: "center" } },
      compassWrap,
      distEl,
      bearingEl,
      el("div", { class: "muted mono", style: { fontSize: "var(--t-xs)", textAlign: "center" } },
        `${(mission.place.name || "TARGET").toUpperCase()} // ${mission.place.category.toUpperCase()}`),
    ),
    el("div", { class: "actions" }, captureBtn, standDownLink),
  );

  return {
    element,
    cleanup: () => {
      off();
      window.removeEventListener("deviceorientation", orientationHandler);
    },
  };
}
