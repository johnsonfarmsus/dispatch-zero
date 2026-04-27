import { el } from "../../dom.js";
import { api } from "../../api.js";
import { clearLastDebrief, clearMissionCache } from "../../flow.js";
import { navigate } from "../../router.js";

export function rate({ id }) {
  let locationRating = null;   // 'up' | 'down' | null
  let missionRating = null;
  let locationReason = null;

  const errEl = el("div", { class: "fault", hidden: true });

  function thumbBtn(label, value, kind) {
    const btn = el("button", { class: "thumb" }, label);
    btn.addEventListener("click", () => {
      if (kind === "location") {
        locationRating = locationRating === value ? null : value;
        renderSelected();
        reasonRow.hidden = locationRating !== "down";
      } else {
        missionRating = missionRating === value ? null : value;
        renderSelected();
      }
    });
    return btn;
  }

  const placeUp = thumbBtn("▲", "up", "location");
  const placeDown = thumbBtn("▼", "down", "location");
  const missionUp = thumbBtn("▲", "up", "mission");
  const missionDown = thumbBtn("▼", "down", "mission");

  function renderSelected() {
    placeUp.classList.toggle("selected", locationRating === "up");
    placeDown.classList.toggle("selected", locationRating === "down");
    missionUp.classList.toggle("selected", missionRating === "up");
    missionDown.classList.toggle("selected", missionRating === "down");
  }

  const reasonSelect = el("select", { name: "location_reason" },
    el("option", { value: "" }, "(no reason given)"),
    el("option", { value: "gone" }, "Place is gone"),
    el("option", { value: "not_found" }, "Couldn't find it"),
    el("option", { value: "inaccessible" }, "Not accessible"),
    el("option", { value: "unsafe" }, "Felt unsafe"),
  );
  reasonSelect.addEventListener("change", () => {
    locationReason = reasonSelect.value || null;
  });

  const reasonRow = el("div", { class: "field", hidden: true },
    el("label", {}, "Reason"),
    reasonSelect,
  );

  const submitBtn = el("button", { class: "primary" }, "Submit");
  const skipLink = el("a", {
    href: "/", "data-route": true, class: "muted",
    style: { textAlign: "center", padding: "var(--s-2)" },
  }, "Skip");

  submitBtn.addEventListener("click", async () => {
    submitBtn.disabled = true;
    errEl.hidden = true;
    try {
      const r = await api.post(`/missions/completions/${id}/rate`, {
        location_rating: locationRating,
        mission_rating: missionRating,
        location_reason: locationReason,
      });
      if (r.ok) {
        clearLastDebrief();
        clearMissionCache();
        await navigate("/", { replace: true });
        return;
      }
      throw new Error(r.data?.detail || "Submit failed.");
    } catch (e) {
      errEl.textContent = e.message;
      errEl.hidden = false;
      submitBtn.disabled = false;
    }
  });

  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "code" }, String(id).slice(0, 8)),
    ),
    el("div", { class: "content stack" },
      el("div", { class: "subtitle" }, "RATE"),
      el("div", { class: "stack", style: { gap: "var(--s-2)" } },
        el("div", { class: "subtitle" }, "THIS PLACE"),
        el("div", { class: "row" }, placeDown, placeUp),
      ),
      reasonRow,
      el("div", { class: "stack", style: { gap: "var(--s-2)" } },
        el("div", { class: "subtitle" }, "THIS MISSION"),
        el("div", { class: "row" }, missionDown, missionUp),
      ),
      errEl,
    ),
    el("div", { class: "actions" }, submitBtn, skipLink),
  );
}
