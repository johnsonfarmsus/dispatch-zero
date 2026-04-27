// Tiny client router. history API, no hash routes. Routes register a renderer
// fn that returns (or resolves to) an HTMLElement.

const _routes = new Map();
let _root = null;
let _notFound = null;

export function defineRoute(path, render) {
  _routes.set(path, render);
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
  const renderer = _routes.get(path) || _notFound;
  if (!renderer) {
    _root.replaceChildren();
    _root.appendChild(document.createTextNode("Not found."));
    return;
  }
  const out = await renderer();
  if (out) _root.replaceChildren(out);
}
