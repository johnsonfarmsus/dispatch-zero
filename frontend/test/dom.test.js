import { test } from "node:test";
import assert from "node:assert/strict";

import { el, text } from "../static/js/dom.js";

test("el: builds a node with tag + class", () => {
  const node = el("div", { class: "screen" });
  assert.equal(node.tagName, "DIV");
  assert.equal(node.className, "screen");
});

test("el: string children become text nodes", () => {
  const node = el("span", {}, "hello");
  assert.equal(node._text, "hello");
});

test("el: null and false children are skipped", () => {
  const node = el("div", {}, "a", null, false, "b");
  assert.equal(node.children.length, 2);
  assert.equal(node._text, "ab");
});

test("el: nested children flatten", () => {
  const node = el("div", {}, [el("span", {}, "x"), el("span", {}, "y")]);
  assert.equal(node.children.length, 2);
});

test("el: style object is applied", () => {
  const node = el("div", { style: { color: "red", padding: "4px" } });
  assert.equal(node.style.color, "red");
  assert.equal(node.style.padding, "4px");
});

test("el: boolean true attribute sets empty string; false/null skipped", () => {
  const on = el("input", { required: true });
  assert.equal(on.getAttribute("required"), "");
  const off = el("input", { hidden: false });
  assert.equal(off.getAttribute("hidden"), null);
});

test("el: on* handlers are registered and fire", () => {
  let clicked = 0;
  const node = el("button", { onClick: () => { clicked++; } });
  node.dispatch("click");
  assert.equal(clicked, 1);
});

test("el: dataset object is applied", () => {
  const node = el("a", { dataset: { route: "true" } });
  assert.equal(node.dataset.route, "true");
});

test("text: produces a text node", () => {
  const t = text("hi");
  assert.equal(t.nodeType, 3);
  assert.equal(t.textContent, "hi");
});
