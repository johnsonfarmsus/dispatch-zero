// Security Protocols — the in-character privacy policy. Public, no auth.
// Designed to fit a single viewport — concise bullets, no prose padding.
import { el } from "../dom.js";

export function securityProtocols() {
  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "— protocols"),
    ),
    el("div", { class: "content stack", style: { gap: "var(--s-3)" } },
      el("div", { class: "subtitle" }, "DECLASSIFIED · INTERNAL"),
      el("div", { class: "title", style: { fontSize: "var(--t-xl)" } },
        "Security Protocols"),

      block("What we keep",
        "Callsign + one-way password hash. No email, no name, no phone, no device ID.",
        "Dispatch records + capture photos (EXIF stripped on save).",
        "One signed session cookie (dz_session). No trackers. No analytics.",
      ),

      block("When we read your location",
        "Request Dispatch — coarse fix to find nearby targets.",
        "Transit — read locally on your device for compass + distance.",
        "Capture — fresh fix sent once to verify range, then discarded.",
        "No location history retained.",
      ),

      block("What leaves our network",
        "Ollama Cloud — place name, callsign, style (mission writing).",
        "OpenStreetMap / Wikipedia / Wikidata — lat/lng queries (no agent ID).",
        "Nothing else.",
      ),

      block("Sharing",
        "Dispatches are private until you tap Save Card or Copy Share Text.",
        "Share URLs use an unguessable token; no public index of history.",
      ),

      block("Removal",
        "Email trevor@johnsonfarms.us with your callsign.",
      ),
    ),
    el("div", { class: "actions" },
      el("a", { href: "/", "data-route": true, class: "muted",
                style: { textAlign: "center", padding: "var(--s-2)" } },
        "← Return"),
    ),
  );
}

function block(heading, ...lines) {
  return el("div", { class: "stack", style: { gap: "var(--s-1)" } },
    el("div", { class: "subtitle" }, heading),
    ...lines.map((line) => el("div", {
      style: { fontSize: "var(--t-sm)", lineHeight: "1.4", color: "var(--text)" },
    }, "· " + line)),
  );
}
