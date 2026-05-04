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

// Build a sharable text + URL and put it on the clipboard. Works for any
// destination (Bluesky, Mastodon, SMS, email, etc.) — user pastes wherever.
export async function copyShareText(shareToken, placeName, statusEl) {
  const url = `${window.location.origin}/c/${shareToken}`;
  const text = placeName
    ? `Dispatched to ${placeName}. ${url}`
    : `Dispatched. ${url}`;
  try {
    await navigator.clipboard.writeText(text);
    statusEl.style.color = "var(--text-muted)";
    statusEl.textContent = "Copied — paste anywhere.";
  } catch (e) {
    statusEl.style.color = "var(--danger)";
    statusEl.textContent = "Copy failed — long-press to copy: " + url;
  }
}
