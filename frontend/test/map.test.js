import { test } from "node:test";
import assert from "node:assert/strict";

import { tileUrlForStyle, TILE_STYLES } from "../static/js/screens/mission/map.js";

test("tileUrlForStyle: pulp gets the warm Voyager basemap", () => {
  assert.match(tileUrlForStyle("pulp"), /rastertiles\/voyager/);
});

test("tileUrlForStyle: agency gets the dark surveillance basemap", () => {
  assert.match(tileUrlForStyle("agency"), /dark_all/);
});

test("tileUrlForStyle: guild gets the pale Positron basemap", () => {
  assert.match(tileUrlForStyle("guild"), /light_all/);
});

test("tileUrlForStyle: unknown style falls back to agency, not a broken URL", () => {
  assert.equal(tileUrlForStyle("wizard"), tileUrlForStyle("agency"));
});

test("tileUrlForStyle: emits Leaflet placeholders and the Carto host", () => {
  const url = tileUrlForStyle("agency");
  assert.match(url, /^https:\/\/\{s\}\.basemaps\.cartocdn\.com\//);
  for (const ph of ["{z}", "{x}", "{y}", "{r}"]) assert.ok(url.includes(ph));
});

test("TILE_STYLES: exactly the three adventure styles are mapped", () => {
  assert.deepEqual(Object.keys(TILE_STYLES).sort(), ["agency", "guild", "pulp"]);
});
