import { el } from "../dom.js";

export function splash() {
  return el("div", { class: "screen" },
    el("div", { class: "header" },
      el("span", {}, "// dispatch zero //"),
      el("span", { class: "muted" }, "receiving"),
    ),
    el("div",
      { class: "content", style: { justifyContent: "center", alignItems: "center" } },
      el("div", { class: "title" }, "Connecting"),
      el("div", { class: "muted mono" }, "Verifying credentials…"),
    ),
    el("div", { class: "actions" }),
  );
}
