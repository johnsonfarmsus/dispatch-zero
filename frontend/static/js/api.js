// Tiny fetch wrapper. Cookies flow automatically (same-origin). 401 returns
// { ok: false, status: 401 } so callers can route to login. Other non-2xx throw.

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

  const r = await fetch(path, init);
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
