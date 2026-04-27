// In-memory user state. The session cookie is the truth; this is just a cache
// for the current page lifecycle.

const _state = { user: null };
const _listeners = new Set();

export function getUser() {
  return _state.user;
}

export function setUser(u) {
  _state.user = u;
  document.body.dataset.style = u?.adventure_style || "agency";
  for (const l of _listeners) l(u);
}

export function clearUser() {
  setUser(null);
}

export function onUserChange(fn) {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}
