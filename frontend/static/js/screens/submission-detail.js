// Submission debrief / detail screen — landed on after a successful
// /submissions/capture, AND reachable from the dossier as a way to view
// any past contribution card. Mirrors history-detail.js for missions.

import { el } from "../dom.js";
import { api } from "../api.js";
import { navigate } from "../router.js";

// Card image carries its own status stamp (PENDING / VERIFIED / RETURNED)
// baked into the JPEG, so we don't render a separate status label on this
// screen anymore. The blurb below the card still differs by status to
// give the submitter the right next-step framing.
const _STATUS_BLURB = {
  pending: (
    "The submission has been received. The Archive will review and re-stamp " +
    "the card once a determination is made. Check your dossier later."
  ),
  approved: (
    "The submission is verified. The coordinates are now in the active registry."
  ),
  returned: (
    "The submission could not be verified. The card stays in your dossier as " +
    "a record. Submit fresh intelligence when you have a clearer record."
  ),
};

export async function submissionDetail({ id }) {
  const r = await api.get(`/submissions/${id}`);
  if (!r.ok) {
    return el("div", { class: "screen" },
      el("div", { class: "content stack" },
        el("div", { class: "fault" }, r.data?.detail || "Submission not found."),
        el("a", {
          href: "/history", "data-route": true, class: "muted",
          style: { textAlign: "center", padding: "var(--s-2)" },
        }, "← Back to Dossier"),
      ),
    );
  }
  const submission = r.data;
  // No header on this screen anymore. The card image itself carries the
  // wordmark, callsign, status stamp, place name, and date, so the screen
  // chrome was duplicating signal that the artifact already provides.
  // Card-only layout reads cleaner end to end, especially when the user
  // is sharing.
  const statusBlurb = _STATUS_BLURB[submission.status] || "";

  // The card is composed server-side with a status stamp baked in, so we
  // just embed the JPEG. If the card is missing (compose failed at submit
  // time), fall back to the raw photo.
  const cardImg = el("img", {
    src: `/submissions/${submission.id}/card.jpg`,
    alt: "Contribution card",
    style: {
      width: "100%",
      maxWidth: "480px",
      aspectRatio: "4 / 5",
      objectFit: "cover",
      border: "1px solid var(--surface-rule)",
      borderRadius: "var(--r-sm)",
      background: "var(--surface-raised)",
    },
  });
  cardImg.addEventListener("error", () => {
    cardImg.src = `/submissions/${submission.id}/photo.jpg`;
  });

  const copyLink = el("button", { type: "button" }, "Copy Share Link");
  copyLink.addEventListener("click", async () => {
    const url = `${window.location.origin}/c/${submission.share_token}`;
    try {
      await navigator.clipboard.writeText(url);
      copyLink.textContent = "Copied";
      setTimeout(() => { copyLink.textContent = "Copy Share Link"; }, 1500);
    } catch (e) {
      copyLink.textContent = "Copy failed";
    }
  });

  const screen = el("div", { class: "screen" },
    el("div", { class: "content stack", style: { alignItems: "center" } },
      cardImg,
      el("p", {
        style: {
          fontSize: "var(--t-sm)", lineHeight: "1.5",
          color: "var(--text-muted)", textAlign: "center",
          maxWidth: "480px",
        },
      }, statusBlurb),
      // Reviewer note (returned submissions only). Rendered as a quoted
      // block so it reads as a message from the Archive rather than part
      // of the user's own description. Pending / approved never have one.
      submission.status === "returned" && submission.review_note
        ? el("blockquote", {
            style: {
              maxWidth: "480px", margin: "0", padding: "var(--s-3) var(--s-4)",
              borderLeft: "2px solid var(--accent-dim)",
              background: "var(--surface-raised)",
              fontSize: "var(--t-sm)", lineHeight: "1.5",
              color: "var(--text)", fontStyle: "italic",
            },
          }, `"${submission.review_note}"`)
        : null,
      // "Now on OpenStreetMap" — the round-trip payoff for the submitter.
      // Shown only when their place was actually published (real node id).
      // This is the moment the whole contribution loop exists to deliver:
      // the person who walked to the place and reported it learns they
      // improved the global map, with a link to their live node.
      submission.osm_node_id
        ? el("div", {
            style: {
              maxWidth: "480px", textAlign: "center",
              padding: "var(--s-3) var(--s-4)",
              border: "1px solid var(--success)",
              borderRadius: "var(--r-sm)",
              background: "var(--surface-raised)",
            },
          },
            el("div", {
              class: "subtitle",
              style: { color: "var(--success)", marginBottom: "var(--s-1)" },
            }, "Now on OpenStreetMap"),
            el("p", {
              style: {
                fontSize: "var(--t-sm)", lineHeight: "1.5",
                color: "var(--text)", margin: "0 0 var(--s-2) 0",
              },
            }, "Your report is now part of the open map the whole world reads from. You put this here."),
            el("a", {
              href: `https://www.openstreetmap.org/node/${submission.osm_node_id}`,
              target: "_blank", rel: "noopener",
              class: "mono",
              style: { fontSize: "var(--t-xs)", color: "var(--accent)" },
            }, `View node #${submission.osm_node_id} ↗`),
          )
        : null,
    ),
    el("div", { class: "actions" },
      copyLink,
      el("a", {
        href: "/history", "data-route": true, class: "muted",
        style: { textAlign: "center", padding: "var(--s-2)" },
      }, "← Back to Dossier"),
    ),
  );
  return screen;
}
