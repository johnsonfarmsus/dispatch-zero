// Submission debrief / detail screen — landed on after a successful
// /submissions/capture, AND reachable from the dossier as a way to view
// any past contribution card. Mirrors history-detail.js for missions.

import { el } from "../dom.js";
import { api } from "../api.js";
import { navigate } from "../router.js";

const _STATUS_LABEL = {
  pending: "Awaiting review",
  approved: "Verified",
  returned: "Returned",
};

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
  const code = String(submission.id).slice(0, 8).toUpperCase();
  const statusLabel = _STATUS_LABEL[submission.status] || submission.status;
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
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, statusLabel),
    ),
    el("div", { class: "content stack", style: { alignItems: "center" } },
      el("div", { class: "subtitle" }, "FILE NUMBER"),
      el("div", { class: "code", style: { fontSize: "var(--t-lg)", letterSpacing: "0.12em" } },
        code),
      cardImg,
      el("p", {
        style: {
          fontSize: "var(--t-sm)", lineHeight: "1.5",
          color: "var(--text-muted)", textAlign: "center",
          maxWidth: "480px",
        },
      }, statusBlurb),
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
