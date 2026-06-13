// Tiny fetch wrapper. Cookies flow automatically (same-origin). 401 returns
// { ok: false, status: 401 } so callers can route to login. Other non-2xx throw.

// Thrown when fetch itself rejects (airplane mode, DNS failure, connection
// reset mid-request) rather than the server returning an error status. Carries
// an in-character message so screens can show it directly without leaking the
// raw browser string ("TypeError: Load failed") that breaks immersion.
export class NetworkError extends Error {
  constructor(cause) {
    super("Dispatch line is unreliable, agent. Signal lost — try again.");
    this.name = "NetworkError";
    this.isNetwork = true;
    this.cause = cause;
  }
}

async function request(method, path, { body, headers, formData } = {}) {
  const init = {
    method,
    credentials: "same-origin",
    headers: { ...headers },
  };
  if (formData) {
    init.body = formData;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers["Content-Type"] = "application/json";
  }

  let r;
  try {
    r = await fetch(path, init);
  } catch (e) {
    // Network-level failure (not an HTTP error status). Normalize to an
    // in-character error rather than letting "Load failed" surface.
    throw new NetworkError(e);
  }
  const ct = r.headers.get("content-type") || "";
  let data;
  if (ct.includes("application/json")) {
    data = await r.json().catch(() => null);
  } else {
    data = await r.text().catch(() => "");
  }

  if (r.status === 401) return { ok: false, status: 401, data };
  if (!r.ok) {
    const err = new Error(data?.detail || `HTTP ${r.status}`);
    err.status = r.status;
    err.data = data;
    throw err;
  }
  return { ok: true, status: r.status, data };
}

export const api = {
  get:      (path)         => request("GET",  path),
  post:     (path, body)   => request("POST", path, { body }),
  postForm: (path, fd)     => request("POST", path, { formData: fd }),
};
