// Security Protocols — public, no auth. Tightened to fit a single mobile
// viewport without scrolling. Header bar already says "protocols", so we
// drop the page title and tighten inter-section gaps.
import { el } from "../dom.js";

export function securityProtocols() {
  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "— protocols"),
    ),
    el("div", { class: "content stack", style: { gap: "var(--s-3)" } },
      block("What we keep",
        "Callsign + password.",
        "Dispatches + captured photos with metadata removed.",
        "One session cookie. No trackers. No analytics.",
        "No email, no name, no phone, no device ID.",
      ),

      block("When we read your location",
        "When you request a dispatch.",
        "When you use the compass.",
        "When you capture a target photo.",
        "No location history retained — used only in the moment.",
      ),

      block("Sharing",
        "Dispatches are private unless you share.",
        "Share URLs use an unguessable token; no public index.",
      ),

      block("What leaves our network",
        "Mission text → Ollama Cloud (place name + callsign + style).",
        "Place lookups → OpenStreetMap, Wikipedia, Wikidata (lat/lng only).",
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
  return el("div", { class: "stack", style: { gap: "2px" } },
    el("div", { class: "subtitle", style: { marginBottom: "2px" } }, heading),
    ...lines.map((line) => el("div", {
      style: { fontSize: "var(--t-sm)", lineHeight: "1.35", color: "var(--text)" },
    }, "· " + line)),
  );
}
