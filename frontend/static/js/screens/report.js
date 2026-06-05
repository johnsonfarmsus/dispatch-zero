// Community POI submission flow. Single screen with:
//   - in-character intro copy (per the user's adventure style)
//   - form: name + category + description
//   - One action slot at the bottom that swaps between two states:
//        State 1: "Add Photo" — a <label> wrapping a hidden file input
//        State 2: "Submit"    — a button that POSTs to /submissions/capture
//     Reusing the same slot keeps the layout tight on small viewports.
//
// We DON'T extract GPS from the photo's EXIF — too many users haven't
// granted Location to the iOS Camera app. We use navigator.geolocation
// (a separate browser permission) and request it AFTER the photo is
// captured, so the user sees the camera + location prompts in obvious
// "I'm submitting this place" context rather than upfront.
//
// Why a <label>+input instead of JS fileInput.click(): iOS Safari
// requires the file dialog to be opened from a synchronous user
// gesture. Any await before .click() (e.g. waiting on getFreshFix)
// breaks the gesture chain and the camera silently never opens.
// Native <label> activation has no such restriction.

import { el } from "../dom.js";
import { api } from "../api.js";
import { getUser } from "../state.js";
import { navigate } from "../router.js";
import { styleMeta } from "../style-meta.js";
import {
  getFreshFix,
  startWatchingPosition,
  stopWatchingPosition,
} from "../flow.js";

const _INTROS = {
  agency: (
    "Operative, the file is always incomplete. Submit coordinates of any " +
    "subject of operational interest in your territory: a marker, an " +
    "installation, a building of note. Entry into the registry follows " +
    "verification. The Archive logs every report."
  ),
  pulp: (
    "Field intelligence is always welcome. If you've come across something " +
    "the Archive doesn't know about, a mural, a forgotten chapel, a marker " +
    "by the road, submit it for cataloguing. Future expeditions will benefit."
  ),
  guild: (
    "The Guild's chronicle is forever unfinished. If you have witnessed a " +
    "site of significance that goes unrecorded, a shrine, a stone, an " +
    "ancient threshold, mark it for inclusion in the codex. The mark is " +
    "yours, the record is the Guild's."
  ),
};

const _CATEGORIES = [
  { value: "mural", label: "Mural" },
  { value: "sculpture", label: "Sculpture" },
  { value: "memorial", label: "Memorial" },
  { value: "historic", label: "Historic building or site" },
  { value: "viewpoint", label: "Viewpoint / scenic" },
  { value: "church", label: "Church" },
  { value: "park", label: "Park / trail / falls" },
  { value: "infrastructure", label: "Infrastructure (bridge, dam, tower)" },
  { value: "civic", label: "Civic landmark (post office)" },
];

export function report() {
  const user = getUser();
  const style = user?.adventure_style || "agency";
  const intro = _INTROS[style] || _INTROS.agency;
  const handler = styleMeta(style);

  // Pre-warm GPS the moment this screen mounts. While the user reads the
  // intro, walks toward the subject, opens the camera, and returns from
  // capture, watchPosition is continuously updating the cached _lastFix
  // with REAL recent positions. Without this, the first time getCurrentPosition
  // gets called is post-camera-return, when iOS may serve a long-stale
  // "last known" fix from before the camera-app suspended Safari (which is
  // what landed the Combine Mural at the submitter's house on the first
  // real-world test). Cleanup stops the watcher on screen unmount.
  startWatchingPosition();

  // Held in closure across the lifecycle of this screen.
  let photoFile = null;
  let photoFix = null;  // { lat, lng, accuracy_m? }

  const nameInput = el("input", {
    type: "text", required: true, maxlength: "200",
    placeholder: "What do people call this place?",
  });
  const categorySelect = el("select", { required: true },
    el("option", { value: "" }, "Pick a category"),
    ..._CATEGORIES.map((c) =>
      el("option", { value: c.value }, c.label),
    ),
  );
  const descInput = el("textarea", {
    maxlength: "140", rows: "2",
    placeholder:
      "A sentence on why — or leave blank if a link below tells the story.",
    style: { resize: "vertical" },
  });
  // Optional link field — separate from the description so we can detect
  // Wikipedia URLs and use them as OSM wikipedia= tags on publish. Any
  // other valid http(s) URL becomes the OSM website= tag. Blank is fine.
  const linkInput = el("input", {
    type: "url",
    maxlength: "500",
    autocapitalize: "off",
    autocorrect: "off",
    spellcheck: "false",
    placeholder: "https://en.wikipedia.org/wiki/... (optional)",
  });

  // Hidden file input. Wrapped by the addPhotoLabel below so iOS opens
  // the camera via native label activation, not via a JS .click() (which
  // would lose the user-gesture context).
  const fileInput = el("input", {
    type: "file", accept: "image/*", capture: "environment",
  });
  // visually hidden but keyboard/tap reachable via the label
  Object.assign(fileInput.style, {
    position: "absolute", width: "1px", height: "1px",
    padding: "0", margin: "-1px", overflow: "hidden",
    clip: "rect(0,0,0,0)", border: "0",
  });

  // Add Photo label (state 1) — styled like a primary button.
  const addPhotoLabel = el("label", {
    class: "primary",
    style: {
      display: "block", textAlign: "center", cursor: "pointer",
      // anchor-style "button" needs explicit padding/border because
      // <label> doesn't pick up button defaults
      padding: "var(--s-3) var(--s-4)",
      border: "1px solid var(--accent)",
      borderRadius: "var(--r-sm)",
      color: "var(--accent)",
      fontFamily: "var(--font-mono)",
      fontSize: "var(--t-base)",
    },
  }, "Add Photo", fileInput);

  // Submit button (state 2). Hidden until photo + GPS are captured.
  const submitBtn = el("button", {
    type: "button", class: "primary",
    style: { display: "none" },
    disabled: true,
  }, "Submit");

  // Small status line below the action slot.
  const photoStatus = el("div", {
    class: "muted mono",
    style: { fontSize: "var(--t-xs)", textAlign: "center", minHeight: "1em" },
  }, "");

  const errEl = el("div", { class: "fault", hidden: true });

  const form = el("form", {
    id: "report-form",
    style: { display: "flex", flexDirection: "column", gap: "var(--s-2)" },
  },
    el("label", { class: "stack", style: { gap: "2px" } },
      el("span", { class: "subtitle" }, "Place name"),
      nameInput,
    ),
    el("label", { class: "stack", style: { gap: "2px" } },
      el("span", { class: "subtitle" }, "Category"),
      categorySelect,
    ),
    el("label", { class: "stack", style: { gap: "2px" } },
      el("span", { class: "subtitle" }, "Why this place? (optional)"),
      descInput,
    ),
    el("label", { class: "stack", style: { gap: "2px" } },
      el("span", { class: "subtitle" }, "Link (optional)"),
      linkInput,
    ),
    errEl,
  );

  const showErr = (msg) => {
    errEl.textContent = msg;
    errEl.hidden = false;
  };

  function refreshSubmitGate() {
    const ready =
      nameInput.value.trim() !== "" &&
      categorySelect.value !== "" &&
      photoFile !== null &&
      photoFix !== null;
    submitBtn.disabled = !ready;
  }
  nameInput.addEventListener("input", refreshSubmitGate);
  categorySelect.addEventListener("change", refreshSubmitGate);

  fileInput.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) {
      photoStatus.style.color = "var(--text-muted)";
      photoStatus.textContent = "";
      return;
    }
    // Photo is captured. Now request GPS — this is where the permission
    // prompt will show on first use. The flow puts both prompts (camera,
    // then location) in obvious "I'm submitting a place" context.
    photoStatus.style.color = "var(--text-muted)";
    photoStatus.textContent = "Locking location…";
    try {
      // 3-second staleness window. The watchPosition we started on mount
      // should be updating _lastFix every few seconds while the user is
      // standing at the subject, so a fresh sub-3s fix is normally already
      // in cache by the time we get here. If not, getFreshFix falls through
      // to getCurrentPosition (maximumAge:0) and waits for a real fix.
      photoFix = await getFreshFix({
        maxAgeMs: 3000,
        enableHighAccuracy: true,
        timeoutMs: 30000,
      });
      photoFile = file;
      // Swap the action slot from Add Photo → Submit.
      addPhotoLabel.style.display = "none";
      submitBtn.style.display = "block";
      photoStatus.style.color = "var(--accent)";
      const accuracy = photoFix.accuracy_m;
      photoStatus.textContent = accuracy
        ? `Photo and location ready (±${Math.round(accuracy)}m).`
        : "Photo and location ready.";
      refreshSubmitGate();
    } catch (err) {
      photoFix = null;
      photoStatus.style.color = "var(--danger)";
      if (err && typeof err.code === "number" && typeof err.PERMISSION_DENIED === "number") {
        if (err.code === 1) {
          photoStatus.textContent = "Location denied. Allow location in browser settings.";
        } else if (err.code === 2) {
          photoStatus.textContent = "GPS unavailable here. Try again outdoors.";
        } else if (err.code === 3) {
          photoStatus.textContent = "Location lookup timed out. Try again.";
        } else {
          photoStatus.textContent = `Location error: ${err.message || "unknown"}`;
        }
      } else {
        photoStatus.textContent = err.message || "Location lookup failed.";
      }
      // Reset the file input so the user can tap the label again to retry
      fileInput.value = "";
    }
  });

  submitBtn.addEventListener("click", async () => {
    errEl.hidden = true;
    if (!nameInput.value.trim()) {
      showErr("Name is required.");
      return;
    }
    if (!categorySelect.value) {
      showErr("Pick a category.");
      return;
    }
    if (descInput.value.length > 140) {
      showErr("Description is too long (max 140 characters).");
      return;
    }
    if (!photoFile || !photoFix) {
      showErr("Add a photo before submitting.");
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Transmitting…";

    try {
      const fd = new FormData();
      fd.append("photo", photoFile);
      fd.append("name", nameInput.value.trim());
      fd.append("category", categorySelect.value);
      fd.append("lat", String(photoFix.lat));
      fd.append("lng", String(photoFix.lng));
      if (descInput.value.trim()) {
        fd.append("description", descInput.value.trim());
      }
      if (linkInput.value.trim()) {
        fd.append("link", linkInput.value.trim());
      }
      const r = await api.postForm("/submissions/capture", fd);
      if (r.ok) {
        await navigate(`/submission/${r.data.id}/debrief`, { replace: true });
        return;
      }
      throw new Error(r.data?.detail || "Submission failed.");
    } catch (err) {
      const msg = err.status === 422
        ? (err.data?.detail || "The Archive could not verify your photo. Try again.")
        : (err.message || "Submission failed.");
      showErr(msg);
      submitBtn.disabled = false;
      submitBtn.textContent = "Submit";
    }
  });

  const screen = el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "report"),
    ),
    el("div", { class: "content stack", style: { gap: "var(--s-2)" } },
      el("div", { class: "row", style: { marginBottom: "var(--s-3)" } },
        el("img", {
          src: `/static/avatars/zero-${style}.png`,
          alt: `Zero (${style} style)`,
          style: {
            width: "44px", height: "44px", borderRadius: "50%",
            border: "1px solid var(--surface-rule)", objectFit: "cover",
          },
        }),
        el("div", { class: "stack", style: { gap: "1px" } },
          el("span", { class: "subtitle" }, handler.handler),
          el("span", { class: "muted", style: { fontSize: "var(--t-sm)", fontStyle: "italic" } },
            handler.org),
        ),
      ),
      el("p", {
        style: {
          fontSize: "var(--t-sm)", lineHeight: "1.4", color: "var(--text)",
          margin: "0 0 var(--s-3) 0",
        },
      }, intro),
      form,
    ),
    el("div", { class: "actions" },
      // Shared action slot: Add Photo label OR Submit button (only one
      // visible at a time). Saves the vertical space that two stacked
      // buttons would otherwise eat.
      addPhotoLabel,
      submitBtn,
      photoStatus,
      el("a", {
        href: "/", "data-route": true, class: "muted",
        style: { textAlign: "center", padding: "var(--s-2)" },
      }, "Back to Home"),
    ),
  );

  // Router calls cleanup on screen unmount. We stop the watcher we started
  // at mount so it doesn't keep draining battery in the background. If the
  // user navigates straight into a mission flow, mission screens call
  // startWatchingPosition() themselves on mount (idempotent), so there's
  // no gap in coverage where the GPS goes cold.
  return { element: screen, cleanup: stopWatchingPosition };
}
