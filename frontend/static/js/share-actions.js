// Shared "Save Card" + "Copy Share Text" actions used by both Debrief and
// the per-completion History detail screen.

// Fetch the mission card and either share it (Web Share API on iOS — lets the
// user save to Photos with one tap) or download it as a fallback.
export async function saveCard(completionId, statusEl, btnEl) {
  btnEl.disabled = true;
  statusEl.style.color = "var(--text-muted)";
  statusEl.textContent = "Composing card…";
  try {
    const r = await fetch(`/missions/completions/${completionId}/card.jpg`, {
      credentials: "same-origin",
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const blob = await r.blob();
    const filename = `dispatch-zero-${String(completionId).slice(0, 8)}.jpg`;

    const file = new File([blob], filename, { type: "image/jpeg" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({ files: [file] });
      statusEl.textContent = "Shared.";
    } else {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      statusEl.textContent = "Downloaded.";
    }
  } catch (e) {
    if (e && e.name === "AbortError") {
      statusEl.textContent = "";
    } else {
      statusEl.style.color = "var(--danger)";
      statusEl.textContent = e.message || "Card unavailable.";
    }
  } finally {
    btnEl.disabled = false;
  }
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
