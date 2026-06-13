// Minimal headless DOM stub for the frontend test runner.
//
// The frontend has no framework and the DOM-touching code it does have
// (dom.js's el(), router.js's render) only uses a small slice of the DOM
// API: createElement/createTextNode, a handful of element properties, and
// replaceChildren/append. Rather than pull in jsdom as a dependency, we
// implement just that slice on globalThis so `node --test` can exercise the
// real modules. Loaded via `--import` so the globals exist before any test
// imports a source module.

class FakeClassList {
  constructor() { this._set = new Set(); }
  add(...cs) { cs.forEach((c) => this._set.add(c)); }
  remove(...cs) { cs.forEach((c) => this._set.delete(c)); }
  contains(c) { return this._set.has(c); }
  toString() { return [...this._set].join(" "); }
}

class FakeNode {
  constructor(tag) {
    this.tagName = (tag || "").toUpperCase();
    this.nodeType = tag === "#text" ? 3 : 1;
    this.children = [];
    this.childNodes = this.children;
    this.attributes = {};
    this.style = {};
    this.dataset = {};
    this._listeners = {};
    this._classList = new FakeClassList();
    this.textContent = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
  }
  get className() { return this._classList.toString(); }
  set className(v) {
    this._classList = new FakeClassList();
    String(v).split(/\s+/).filter(Boolean).forEach((c) => this._classList.add(c));
  }
  get classList() { return this._classList; }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] ?? null; }
  appendChild(node) { this.children.push(node); node.parentNode = this; return node; }
  append(...nodes) { nodes.forEach((n) => this.appendChild(n)); }
  replaceChildren(...nodes) {
    this.children.length = 0;
    nodes.forEach((n) => this.appendChild(n));
  }
  addEventListener(type, fn) {
    (this._listeners[type] ||= []).push(fn);
  }
  removeEventListener(type, fn) {
    this._listeners[type] = (this._listeners[type] || []).filter((f) => f !== fn);
  }
  dispatch(type, event = {}) {
    (this._listeners[type] || []).forEach((fn) => fn(event));
  }
  querySelector() { return null; }
  // Test helper: recursively collect text content. Includes this node's
  // own textContent (set directly, e.g. node.textContent = "x") plus any
  // child text. Real code uses one or the other, not both, so this doesn't
  // double-count.
  get _text() {
    if (this.nodeType === 3) return this.textContent;
    return (this.textContent || "") + this.children.map((c) => c._text).join("");
  }
}

const fakeDocument = {
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (s) => {
    const n = new FakeNode("#text");
    n.textContent = String(s);
    return n;
  },
  addEventListener() {},
  getElementById: () => new FakeNode("div"),
};

globalThis.document = fakeDocument;
globalThis.window = {
  location: { pathname: "/", search: "" },
  history: { pushState() {}, replaceState() {} },
  addEventListener() {},
  confirm: () => true,
};
// Node 21+ provides a read-only global `navigator` (no geolocation), which
// is exactly what the watch code needs to early-return — so we leave it
// alone rather than reassign (it has only a getter and can't be replaced).

export { FakeNode };
