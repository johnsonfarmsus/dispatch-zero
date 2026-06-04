// Community POI submission flow. Single screen with:
//   - in-character intro copy (per the user's adventure style)
//   - form: name + category + description
//   - "Add Photo" button: requests browser GPS, then opens camera. After
//     both succeed the captured file + coords are held in screen state.
//   - "Submit" button (primary, footer): only enabled when name + category
//     + photo + GPS are all present. Posts to /submissions/capture and
//     navigates to the contribution-card debrief.
//
// We DON'T extract GPS from the photo's EXIF — too many users haven't
// granted Location to the iOS Camera app, and asking them to fix it is
// worse UX than letting the browser request its own location permission
// independently via navigator.geolocation.

import { el } from "../dom.js";
import { api } from "../api.js";
import { getUser } from "../state.js";
import { navigate } from "../router.js";
import { styleMeta } from "../style-meta.js";
import { getFreshFix } from "../flow.js";

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

  // ----- state held across the lifecycle of this screen -----
  // photoFile and photoFix are both captured by the Add Photo button.
  // Submit only posts when both are present alongside name + category.
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
      "Optional. One sentence on why this place is worth a dispatch.",
    style: { resize: "vertical" },
  });

  // Hidden camera input. addPhotoBtn triggers .click() on this AFTER
  // GPS has been acquired; on file change we store the file + GPS and
  // update the UI.
  const fileInput = el("input", {
    type: "file", accept: "image/*", capture: "environment",
    hidden: true,
  });

  const addPhotoBtn = el("button", {
    type: "button",
    style: { width: "100%" },
  }, "Add Photo");
  // Small line under the button reporting state: "" / "Acquiring location…" /
  // "Photo attached ✓" / error.
  const photoStatus = el("div", {
    class: "muted mono",
    style: { fontSize: "var(--t-xs)", textAlign: "center", minHeight: "1em" },
  }, "");

  const submitBtn = el("button", {
    type: "button",
    form: "report-form",
    class: "primary",
    disabled: true,
  }, "Submit");
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
    el("div", { class: "stack", style: { gap: "2px" } },
      addPhotoBtn,
      photoStatus,
    ),
    errEl,
  );

  const showErr = (msg) => {
    errEl.textContent = msg;
    errEl.hidden = false;
  };

  // Submit is gated on name + category + photo + GPS. Recompute on every
  // input change so the button comes alive at exactly the right moment.
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

  addPhotoBtn.addEventListener("click", async () => {
    errEl.hidden = true;
    addPhotoBtn.disabled = true;
    photoStatus.style.color = "var(--text-muted)";
    photoStatus.textContent = "Acquiring location…";
    try {
      // Get GPS FIRST, then open the camera. If the browser denies location
      // we don't waste a camera invocation before failing.
      photoFix = await getFreshFix({
        maxAgeMs: 60000,
        enableHighAccuracy: true,
        timeoutMs: 30000,
      });
      photoStatus.textContent = "Location locked. Opening camera…";
      fileInput.value = "";  // ensure change fires even if same file picked twice
      fileInput.click();
    } catch (e) {
      photoFix = null;
      photoStatus.style.color = "var(--danger)";
      if (e && typeof e.code === "number" && typeof e.PERMISSION_DENIED === "number") {
        if (e.code === 1) {
          photoStatus.textContent = "Location denied. Allow location in browser settings.";
        } else if (e.code === 2) {
          photoStatus.textContent = "GPS unavailable here. Try again outdoors.";
        } else if (e.code === 3) {
          photoStatus.textContent = "Location lookup timed out. Try again.";
        } else {
          photoStatus.textContent = `Location error: ${e.message || "unknown"}`;
        }
      } else {
        photoStatus.textContent = e.message || "Location lookup failed.";
      }
      addPhotoBtn.disabled = false;
      refreshSubmitGate();
    }
  });

  fileInput.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    if (!file) {
      // User cancelled the camera. Reset to the "Add Photo" state but keep
      // any GPS fix we acquired; they can hit the button again.
      photoStatus.style.color = "var(--text-muted)";
      photoStatus.textContent = photoFix ? "Location ready. Try the photo again." : "";
      addPhotoBtn.disabled = false;
      return;
    }
    photoFile = file;
    photoStatus.style.color = "var(--accent)";
    photoStatus.textContent = "Photo attached. Ready to submit.";
    addPhotoBtn.textContent = "Replace Photo";
    addPhotoBtn.disabled = false;
    refreshSubmitGate();
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
    addPhotoBtn.disabled = true;

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
      addPhotoBtn.disabled = false;
      refreshSubmitGate();
    }
  });

  const screen = el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "report"),
    ),
    // Tight content stack (--s-2) so this fits in browser viewport without
    // scroll. The single-page gameplay vibe means everything (handler card,
    // intro, full form) needs to land above the fold.
    el("div", { class: "content stack", style: { gap: "var(--s-2)" } },
      // marginBottom on the handler row buys back the extra breathing
      // space ABOVE the card (screen grid gap --s-5 + header padding) so
      // the visual gaps above and below the handler card match.
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
      fileInput,
    ),
    el("div", { class: "actions" },
      submitBtn,
      el("a", {
        href: "/", "data-route": true, class: "muted",
        style: { textAlign: "center", padding: "var(--s-2)" },
      }, "Back to Home"),
    ),
  );

  return screen;
}
