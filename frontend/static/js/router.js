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
  const out = await renderer(params || {});
  if (out && typeof out === "object" && "element" in out) {
    _currentCleanup = out.cleanup || null;
    _root.replaceChildren(out.element);
  } else if (out) {
    _root.replaceChildren(out);
  }
}
