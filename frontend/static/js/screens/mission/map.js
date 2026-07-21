import { el } from "../../dom.js";
import {
  loadMission, startWatchingPosition, stopWatchingPosition,
  onFix, onFixError, geoErrorMessage, getLastFix,
  distanceM, formatDistance,
} from "../../flow.js";
import { navigate } from "../../router.js";

// Per-style Carto basemaps (project doc: warm explorer's map for pulp,
// black surveillance map for agency, pale old-world cartography for guild).
// Exported for tests.
export const TILE_STYLES = {
  pulp: "rastertiles/voyager",
  agency: "dark_all",
  guild: "light_all",
};

export function tileUrlForStyle(style) {
  const path = TILE_STYLES[style] || TILE_STYLES.agency;
  return `https://{s}.basemaps.cartocdn.com/${path}/{z}/{x}/{y}{r}.png`;
}

// Inline SVG markers (no external images — the default Leaflet marker PNGs
// are not vendored). Colors resolve from the style-scoped CSS accent.
function targetIconSvg(accent) {
  return `<svg viewBox="0 0 32 40" xmlns="http://www.w3.org/2000/svg">
    <path d="M16 1 L31 16 L16 39 L1 16 Z" fill="${accent}" stroke="#0e0c0a" stroke-width="2"/>
    <circle cx="16" cy="15" r="4" fill="#0e0c0a"/>
  </svg>`;
}

function userIconSvg(accent) {
  return `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <circle cx="12" cy="12" r="10" fill="${accent}" fill-opacity="0.25"/>
    <circle cx="12" cy="12" r="5" fill="${accent}" stroke="#0e0c0a" stroke-width="1.5"/>
  </svg>`;
}

export async function missionMap({ id }) {
  const mission = await loadMission(id);
  const code = String(mission.id).slice(0, 8);
  const style = document.body.dataset.style || "agency";
  const accent =
    getComputedStyle(document.body).getPropertyValue("--accent").trim() ||
    "#4ec5d6";

  const mapEl = el("div", { class: "map-canvas" });
  const distEl = el("span", { class: "code" }, "ACQUIRING FIX");

  const backBtn = el("button", { class: "primary" }, "Return to Transit");
  backBtn.addEventListener("click", () => navigate(`/mission/${mission.id}/transit`));

  const element = el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// tactical map //"),
      el("span", { class: "code" }, code),
    ),
    el("div", { class: "content map-content" }, mapEl),
    el("div", { class: "map-status mono" },
      el("span", { class: "muted" },
        `${(mission.place.name || "TARGET").toUpperCase()}`),
      distEl,
    ),
    el("div", { class: "actions" }, backBtn),
  );

  let map = null;
  let userMarker = null;
  let leaflet = null;
  let disposed = false;

  // Leaflet needs a laid-out container to size itself; the router mounts
  // `element` only after this renderer resolves, so map construction is
  // deferred to a frame after mount instead of running here directly.
  requestAnimationFrame(async () => {
    if (disposed) return;
    try {
      leaflet = await import("../../../vendor/leaflet/leaflet-src.esm.js");
    } catch {
      mapEl.textContent = "Map assets failed to load. The compass still works, agent.";
      mapEl.classList.add("map-error");
      return;
    }
    if (disposed) return;

    const target = [mission.place.lat, mission.place.lng];
    map = leaflet.map(mapEl, {
      zoomControl: false,        // pinch/double-tap zoom; controls clutter a phone map
      attributionControl: true,  // Carto/OSM attribution is a license requirement
    });

    leaflet.tileLayer(tileUrlForStyle(style), {
      subdomains: "abcd",
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
    }).addTo(map);

    leaflet.marker(target, {
      icon: leaflet.divIcon({
        className: "map-pin",
        html: targetIconSvg(accent),
        iconSize: [32, 40],
        iconAnchor: [16, 39],
      }),
    }).addTo(map);

    const fix = getLastFix();
    if (fix) {
      placeUser(fix);
      map.fitBounds(leaflet.latLngBounds([fix.lat, fix.lng], target).pad(0.25));
    } else {
      map.setView(target, 16);
    }
  });

  function placeUser(fix) {
    if (!map || !leaflet) return;
    const at = [fix.lat, fix.lng];
    if (userMarker) {
      userMarker.setLatLng(at);
    } else {
      userMarker = leaflet.marker(at, {
        icon: leaflet.divIcon({
          className: "map-pin",
          html: userIconSvg(accent),
          iconSize: [24, 24],
          iconAnchor: [12, 12],
        }),
        interactive: false,
      }).addTo(map);
    }
  }

  startWatchingPosition();
  const off = onFix((fix) => {
    placeUser(fix);
    const d = distanceM(fix.lat, fix.lng, mission.place.lat, mission.place.lng);
    distEl.textContent = formatDistance(d).toUpperCase();
    distEl.style.color = "";
  });
  const offErr = onFixError((err) => {
    distEl.textContent = geoErrorMessage(err).toUpperCase();
    distEl.style.color = "var(--danger)";
  });

  return {
    element,
    cleanup: () => {
      disposed = true;
      off();
      offErr();
      stopWatchingPosition();
      if (map) map.remove();
    },
  };
}
