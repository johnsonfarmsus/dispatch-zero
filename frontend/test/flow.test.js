import { test } from "node:test";
import assert from "node:assert/strict";

import {
  distanceM, bearingDeg, bearingCompassLabel, formatDistance,
  geoErrorMessage, onFix, onFixError, getLastFix,
  setLastDebrief, getLastDebrief, clearLastDebrief,
} from "../static/js/flow.js";

test("distanceM: zero for same point", () => {
  assert.equal(distanceM(47.5, -118.25, 47.5, -118.25), 0);
});

test("distanceM: ~111km per degree of latitude", () => {
  const d = distanceM(47.0, -118.0, 48.0, -118.0);
  assert.ok(d > 110_000 && d < 112_000, `got ${d}`);
});

test("bearingDeg: due north is ~0", () => {
  const b = bearingDeg(47.0, -118.0, 48.0, -118.0);
  assert.ok(b < 1 || b > 359, `got ${b}`);
});

test("bearingDeg: due east is ~90", () => {
  const b = bearingDeg(47.0, -118.0, 47.0, -117.0);
  assert.ok(Math.abs(b - 90) < 1, `got ${b}`);
});

test("bearingCompassLabel: cardinal directions", () => {
  assert.equal(bearingCompassLabel(0), "N");
  assert.equal(bearingCompassLabel(90), "E");
  assert.equal(bearingCompassLabel(180), "S");
  assert.equal(bearingCompassLabel(270), "W");
});

test("formatDistance: meters under 1km, km above", () => {
  assert.equal(formatDistance(450), "450m");
  assert.equal(formatDistance(1500), "1.50km");
  assert.equal(formatDistance(null), "—");
  assert.equal(formatDistance(NaN), "—");
});

test("geoErrorMessage: maps GeolocationPositionError codes", () => {
  assert.match(geoErrorMessage({ code: 1 }), /denied/i);
  assert.match(geoErrorMessage({ code: 2 }), /signal/i);
  assert.match(geoErrorMessage({ code: 3 }), /long|sky/i);
  assert.match(geoErrorMessage({}), /unavailable|permission/i);
});

test("onFix / onFixError: subscribe + unsubscribe", () => {
  let fixCalls = 0;
  const off = onFix(() => { fixCalls++; });
  assert.equal(typeof off, "function");
  off();  // unsubscribe should not throw
  let errCalls = 0;
  const offErr = onFixError(() => { errCalls++; });
  offErr();
  assert.equal(fixCalls, 0);
  assert.equal(errCalls, 0);
});

test("lastDebrief: set / get / clear", () => {
  assert.equal(getLastDebrief(), null);
  setLastDebrief({ id: "abc" });
  assert.deepEqual(getLastDebrief(), { id: "abc" });
  clearLastDebrief();
  assert.equal(getLastDebrief(), null);
});

test("getLastFix: null before any fix", () => {
  assert.equal(getLastFix(), null);
});
