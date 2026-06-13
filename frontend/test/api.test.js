import { test, afterEach } from "node:test";
import assert from "node:assert/strict";

import { api, NetworkError } from "../static/js/api.js";

function fakeResponse({ status = 200, json = null, textBody = "" } = {}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: () => (json != null ? "application/json" : "text/plain") },
    json: async () => json,
    text: async () => textBody,
  };
}

afterEach(() => { delete globalThis.fetch; });

test("NetworkError carries an in-character message + isNetwork flag", () => {
  const e = new NetworkError(new Error("Load failed"));
  assert.equal(e.isNetwork, true);
  assert.match(e.message, /dispatch line|signal/i);
});

test("request: fetch rejection becomes a NetworkError", async () => {
  globalThis.fetch = async () => { throw new TypeError("Load failed"); };
  await assert.rejects(() => api.get("/anything"), (err) => {
    assert.ok(err instanceof NetworkError);
    assert.equal(err.isNetwork, true);
    return true;
  });
});

test("request: 401 returns ok:false rather than throwing", async () => {
  globalThis.fetch = async () => fakeResponse({ status: 401, json: { detail: "nope" } });
  const r = await api.get("/auth/me");
  assert.equal(r.ok, false);
  assert.equal(r.status, 401);
});

test("request: non-2xx throws an error carrying status + data", async () => {
  globalThis.fetch = async () => fakeResponse({ status: 422, json: { detail: "bad" } });
  await assert.rejects(() => api.post("/x", {}), (err) => {
    assert.equal(err.status, 422);
    assert.equal(err.data.detail, "bad");
    return true;
  });
});

test("request: 2xx returns ok:true + parsed data", async () => {
  globalThis.fetch = async () => fakeResponse({ status: 200, json: { hello: "world" } });
  const r = await api.get("/ok");
  assert.equal(r.ok, true);
  assert.deepEqual(r.data, { hello: "world" });
});
