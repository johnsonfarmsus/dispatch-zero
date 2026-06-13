import { test } from "node:test";
import assert from "node:assert/strict";

import { defineRoute, defineNotFound, init, navigate } from "../static/js/router.js";
import { el } from "../static/js/dom.js";

// Routes are module-global; define them once for the whole file.
let cleanupRan = 0;
defineRoute("/home", () => el("div", {}, "HOME SCREEN"));
defineRoute("/boom", () => { throw new Error("kaboom"); });
defineRoute("/withcleanup", () => ({
  element: el("div", {}, "HAS CLEANUP"),
  cleanup: () => { cleanupRan++; },
}));
defineNotFound(() => el("div", {}, "NOT FOUND"));

const root = el("div", {});
init(root);  // renders the initial path "/" -> notFound

test("renders a matched route into the root", async () => {
  await navigate("/home");
  assert.match(root._text, /HOME SCREEN/);
});

test("unmatched path falls through to notFound", async () => {
  await navigate("/no-such-route");
  assert.match(root._text, /NOT FOUND/);
});

test("error boundary: a throwing renderer paints the fault screen, not a crash", async () => {
  await navigate("/boom");  // must not reject
  assert.match(root._text, /Transmission interrupted/i);
  assert.match(root._text, /Retry/);
});

test("cleanup hook runs when navigating away from a screen that defined one", async () => {
  await navigate("/withcleanup");
  const before = cleanupRan;
  await navigate("/home");  // leaving /withcleanup should run its cleanup
  assert.equal(cleanupRan, before + 1);
});
