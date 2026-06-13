// Tiny client router with :param support and per-screen cleanup hooks.

const _routes = [];   // [{ regex, paramNames, render }]
let _root = null;
let _notFound = null;
let _currentCleanup = null;

function compile(pattern) {
  const paramNames = [];
  const regexStr = pattern.replace(/:([a-zA-Z_][a-zA-Z0-9_]*)/g, (_, name) => {
    paramNames.push(name);
    return "([^/]+)";
  });
  return { regex: new RegExp(`^${regexStr}$`), paramNames };
}

export function defineRoute(pattern, render) {
  const { regex, paramNames } = compile(pattern);
  _routes.push({ regex, paramNames, render });
}

export function defineNotFound(render) {
  _notFound = render;
}

export function init(rootElement) {
  _root = rootElement;
  window.addEventListener("popstate", () => render(window.location.pathname));
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-route]");
    if (!a) return;
    e.preventDefault();
    navigate(a.getAttribute("href"));
  });
  render(window.location.pathname);
}

export async function navigate(path, { replace = false } = {}) {
  if (replace) {
    window.history.replaceState({}, "", path);
  } else {
    window.history.pushState({}, "", path);
  }
  await render(path);
}

// In-character fault screen shown when a renderer throws (a failed fetch
// mid-mission, an undefined field, etc.). Without this boundary, a thrown
// renderer would abort the navigation and leave the previous screen mounted
// but with its cleanup already run — a half-dead UI with no recovery. The
// retry re-runs the current path.
function _faultScreen(err) {
  const wrap = document.createElement("div");
  wrap.className = "screen";
  const content = document.createElement("div");
  content.className = "content stack";
  content.style.justifyContent = "center";
  content.style.alignItems = "center";
  content.style.textAlign = "center";

  const title = document.createElement("div");
  title.className = "title";
  title.textContent = "Transmission interrupted.";
  const msg = document.createElement("div");
  msg.className = "muted";
  msg.style.maxWidth = "320px";
  msg.textContent = err && err.isNetwork
    ? "The dispatch line is unreliable, agent. Check your signal and try again."
    : "Something went wrong on this channel. Try again, agent.";

  const retry = document.createElement("button");
  retry.className = "primary";
  retry.textContent = "Retry";
  retry.style.marginTop = "var(--s-4)";
  retry.addEventListener("click", () => render(window.location.pathname));

  const home = document.createElement("a");
  home.href = "/";
  home.setAttribute("data-route", "true");
  home.className = "muted";
  home.style.marginTop = "var(--s-3)";
  home.style.padding = "var(--s-2)";
  home.textContent = "Back to Home";

  content.append(title, msg, retry, home);
  wrap.appendChild(content);
  return wrap;
}

async function render(path) {
  if (_currentCleanup) {
    try { _currentCleanup(); } catch { /* ignore */ }
    _currentCleanup = null;
  }

  let matched = null;
  let params = null;
  for (const route of _routes) {
    const m = path.match(route.regex);
    if (m) {
      matched = route;
      params = {};
      route.paramNames.forEach((name, i) => { params[name] = decodeURIComponent(m[i + 1]); });
      break;
    }
  }
  const renderer = matched?.render || _notFound;
  if (!renderer) {
    _root.replaceChildren();
    _root.appendChild(document.createTextNode("Not found."));
    return;
  }
  try {
    const out = await renderer(params || {});
    if (out && typeof out === "object" && "element" in out) {
      _currentCleanup = out.cleanup || null;
      _root.replaceChildren(out.element);
    } else if (out) {
      _root.replaceChildren(out);
    }
  } catch (err) {
    // Renderer threw (failed fetch, bad data). Paint the fault screen
    // instead of leaving a half-dead UI.
    _currentCleanup = null;
    _root.replaceChildren(_faultScreen(err));
  }
}
