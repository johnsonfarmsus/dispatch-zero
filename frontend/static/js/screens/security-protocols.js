// Security Protocols — the in-character privacy policy. Public page; no auth.
import { el } from "../dom.js";

export function securityProtocols() {
  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "— protocols"),
    ),
    el("div", { class: "content stack scrollable",
                 style: { gap: "var(--s-4)", paddingBottom: "var(--s-6)" } },
      el("div", { class: "subtitle" }, "DECLASSIFIED · INTERNAL"),
      el("div", { class: "title", style: { fontSize: "var(--t-2xl)" } },
        "Security Protocols"),
      el("div", {
        style: { fontFamily: "var(--font-serif)", fontSize: "var(--t-base)",
                 lineHeight: "1.6", color: "var(--text-muted)" },
      },
        "An operational record of what the dispatch line collects, what it ",
        "retains, and what — if anything — it forwards to other networks. ",
        "We don't expect you to take this on faith. The relevant code is on ",
        "disk.",
      ),

      section("Identity & credentials",
        "You sign on with a callsign and a password. We do not collect your " +
        "real name, your email, your phone number, your date of birth, your " +
        "device fingerprint, or any third-party identifier.",
        "Your callsign and an argon2id hash of your password are the only " +
        "records we keep against your account. The hash is one-way; it is " +
        "not a stored copy of your password.",
      ),

      section("Cookies",
        "One cookie is set, and only one: dz_session. It carries your user " +
        "id, signed against the dispatch line's secret. It exists to keep " +
        "you logged in between requests.",
        "No tracking cookies. No third-party cookies. No analytics beacons. " +
        "No advertising network has any presence on this site.",
      ),

      section("Location",
        "Your device's location is consulted at three specific moments:",
        "• Request Dispatch — a coarse fix is sent to identify nearby " +
        "targets within your radius.",
        "• Transit — your device's live position is read locally to draw " +
        "the compass and distance readout. That stream does not leave " +
        "your device.",
        "• Proof of capture — a fresh, accurate fix accompanies the photo " +
        "upload so we can verify you are within range of the target. After " +
        "verification it is discarded. The coordinates are not written to " +
        "the dispatch record.",
        "We do not maintain a location history for any agent.",
      ),

      section("Photographs",
        "Capture photos are saved on our server with EXIF metadata — " +
        "including any embedded GPS coordinates and capture timestamp — " +
        "stripped before storage.",
        "A composed mission card is generated alongside each photo for " +
        "sharing. Both files are kept so prior dispatches remain visible " +
        "in your dossier and shared links continue to function.",
      ),

      section("What we forward to other networks",
        "Mission generation. The target's name, category, description, your " +
        "callsign, and your selected organization style are forwarded to " +
        "Ollama Cloud to compose your briefing. Ollama receives no other " +
        "identifiers.",
        "Target discovery. Latitude/longitude radius queries are forwarded " +
        "to public OpenStreetMap (Overpass), Wikipedia geosearch, and " +
        "Wikidata. No agent identifier is attached to these queries.",
        "Nothing else is forwarded. There are no analytics integrations, " +
        "no advertising networks, no social media SDKs, no external " +
        "telemetry of any kind.",
      ),

      section("Retention",
        "• Your account record persists until you ask for it to be removed.",
        "• Your dispatch records — completions and their associated " +
        "photographs and cards — are retained so your dossier and shared " +
        "links remain intact.",
        "• External API responses are cached for between 7 and 90 days. " +
        "These caches are keyed by latitude/longitude or place identifier; " +
        "they do not carry user identifiers.",
      ),

      section("Public exposure",
        "A dispatch becomes externally visible only when you choose to " +
        "share it — by tapping Save Card or Copy Share Text on a dispatch " +
        "in your dossier.",
        "The resulting URL takes the form /c/<token> where the token is an " +
        "unguessable ~56-bit identifier. The dispatch line does not " +
        "publish, enumerate, or index any agent's history. Until you " +
        "share a link, your dossier remains private.",
      ),

      section("Removal",
        "Removal of your callsign and all associated dispatches is " +
        "currently handled by hand. To request removal, reach the dispatch " +
        "line at trevor@johnsonfarms.us with your callsign in the message.",
      ),

      el("div", {
        style: { marginTop: "var(--s-3)", color: "var(--text-faint)",
                 fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)",
                 textAlign: "right" },
      }, "— end of document"),
    ),
    el("div", { class: "actions" },
      el("a", { href: "/", "data-route": true, class: "muted",
                style: { textAlign: "center", padding: "var(--s-2)" } },
        "← Return"),
    ),
  );
}

function section(heading, ...paragraphs) {
  return el("div", { class: "stack", style: { gap: "var(--s-2)" } },
    el("div", { class: "subtitle" }, heading),
    ...paragraphs.map((p) => el("div", {
      style: { fontFamily: "var(--font-serif)", fontSize: "var(--t-base)",
               lineHeight: "1.6", color: "var(--text)" },
    }, p)),
  );
}
