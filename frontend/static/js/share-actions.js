// Shared "Save Card" + "Copy Share Text" actions used by both Debrief and
// the per-completion History detail screen.

// Open the card image in a new tab. From there:
//   iOS  — long-press the image → Save to Photos
//   Android — image menu → Save / Share
//   Desktop — right-click → Save image as
// Simpler and more predictable than the Web Share API, which on iOS
// sometimes routed file shares through targets that fell back to a
// Google search.
export function saveCard(completionId) {
  window.open(
    `/missions/completions/${completionId}/card.jpg`,
    "_blank",
    "noopener",
  );
}

// Copy the share URL (and only the URL) to the clipboard. Pasting the bare
// URL into Bluesky/Mastodon/Discord/Slack lets each platform unfurl it
// using the OG tags on the public /c/<token> page — no extra preamble
// needed (and apps that don't unfurl can show the link as-is).
export async function copyShareText(shareToken, _placeName, statusEl) {
  const url = `${window.location.origin}/c/${shareToken}`;
  try {
    await navigator.clipboard.writeText(url);
    statusEl.style.color = "var(--text-muted)";
    statusEl.textContent = "Link copied.";
  } catch (e) {
    statusEl.style.color = "var(--danger)";
    statusEl.textContent = "Copy failed — long-press to copy: " + url;
  }
}
