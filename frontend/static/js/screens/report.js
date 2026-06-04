// Community POI submission flow. Single screen with:
//   - in-character intro copy (per the user's adventure style)
//   - form: name + category + description
//   - Submit button that validates the form then triggers the device camera
//   - on photo capture, POSTs to /submissions/capture and navigates to the
//     debrief screen which shows the composed contribution card
//
// The mission capture screen (screens/mission/capture.js) was the pattern;
// the difference here is the form lives on the same screen as the camera
// trigger rather than being driven by a server-side mission.

import { el } from "../dom.js";
import { api } from "../api.js";
import { getUser } from "../state.js";
import { navigate } from "../router.js";
import { styleMeta } from "../style-meta.js";

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

  // Hidden camera input. Submit triggers .click() on this; on file change
  // we package the form + the file and POST.
  const fileInput = el("input", {
    type: "file", accept: "image/*", capture: "environment",
    hidden: true,
  });

  // Submit button lives in the .actions footer (outside the form element)
  // for layout reasons. The `form="report-form"` attribute associates them
  // via HTML5 so submit + validation still fire — clicking the button
  // dispatches the form's submit event the same way an in-form button would.
  const submitBtn = el("button", {
    type: "submit", form: "report-form", class: "primary",
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
    errEl,
  );

  const showErr = (msg) => {
    errEl.textContent = msg;
    errEl.hidden = false;
  };

  form.addEventListener("submit", (e) => {
    e.preventDefault();
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
    // Form is valid — open the camera.
    fileInput.click();
  });

  fileInput.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    errEl.hidden = true;
    submitBtn.disabled = true;
    submitBtn.textContent = "Transmitting…";

    try {
      const fd = new FormData();
      fd.append("photo", file);
      fd.append("name", nameInput.value.trim());
      fd.append("category", categorySelect.value);
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
      fileInput.value = "";
    }
  });

  const screen = el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "report"),
    ),
    // Tight content stack (--s-2) so this fits in browser viewport without
    // scroll. The single-page gameplay vibe means everything — handler card,
    // intro, full form — needs to land above the fold.
    el("div", { class: "content stack", style: { gap: "var(--s-2)" } },
      // marginBottom on the handler row buys back the extra breathing
      // space ABOVE the card (screen grid gap --s-5 + header padding) so
      // the visual gaps above and below the handler card match.
      el("div", { class: "row", style: { marginBottom: "var(--s-3)" } },
        el("img", {
          src: `/static/avatars/zero-${style}.png`,
          alt: `Zero — ${style} style`,
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
      // margin:0 strips the default ~16px top/bottom <p> margin browsers
      // apply. marginBottom: var(--s-3) buys back the extra space so the
      // gap below the paragraph matches the gap above it (which carries
      // the handler-row marginBottom).
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
