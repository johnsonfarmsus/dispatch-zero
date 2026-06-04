// Security Protocols — public, no auth. Content grew past one viewport once
// the Source & license block landed, so the content area is .scrollable —
// the header band ("// dispatch zero //") and the actions footer ("About
// this project →" / "← Return") stay pinned and the middle scrolls. Inter-
// section gaps stay tight so on a roomy phone you still see most sections
// without scrolling.
import { el } from "../dom.js";

export function securityProtocols() {
  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "protocols"),
    ),
    el("div", { class: "content stack scrollable", style: { gap: "var(--s-3)" } },
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
        "No location history retained. Used only in the moment.",
      ),

      block("Sharing",
        "Dispatches are private unless you share.",
        "Share URLs use an unguessable token; no public index.",
      ),

      block("What leaves our network",
        "Mission text → Ollama Cloud (place name + callsign + style).",
        "Place lookups → OpenStreetMap, Wikipedia, Wikidata (lat/lng only).",
      ),

      // Source + license block. Constructed manually (rather than via block())
      // so the GitHub URL can be a real clickable anchor instead of plain text.
      el("div", { class: "stack", style: { gap: "2px" } },
        el("div", { class: "subtitle", style: { marginBottom: "2px" } },
          "Source & license"),
        el("div", {
          style: { fontSize: "var(--t-sm)", lineHeight: "1.35", color: "var(--text)" },
        },
          "· Source: ",
          el("a", {
            href: "https://github.com/johnsonfarmsus/dispatch-zero",
            target: "_blank", rel: "noopener",
            style: { color: "var(--text)", borderBottom: "1px dotted currentColor",
                     textDecoration: "none" },
          }, "github.com/johnsonfarmsus/dispatch-zero"),
        ),
        el("div", {
          style: { fontSize: "var(--t-sm)", lineHeight: "1.35", color: "var(--text)" },
        }, "· License: AGPL-3.0. Modifications must stay open."),
      ),
    ),
    el("div", { class: "actions" },
      el("a", {
        href: "https://ataary.com/tag/dispatchzero/",
        target: "_blank", rel: "noopener",
        class: "muted",
        style: { textAlign: "center", padding: "var(--s-2)" },
      }, "About this project →"),
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
