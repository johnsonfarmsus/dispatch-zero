// Security Protocols — public, no auth. Single viewport, no scroll.
import { el } from "../dom.js";

export function securityProtocols() {
  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "— protocols"),
    ),
    el("div", { class: "content stack" },
      el("div", { class: "title", style: { fontSize: "var(--t-xl)" } },
        "Security Protocols"),

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
  return el("div", { class: "stack", style: { gap: "var(--s-1)" } },
    el("div", { class: "subtitle" }, heading),
    ...lines.map((line) => el("div", {
      style: { fontSize: "var(--t-sm)", lineHeight: "1.5", color: "var(--text)" },
    }, "· " + line)),
  );
}
