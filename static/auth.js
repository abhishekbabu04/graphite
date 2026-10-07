/* Sign in with Google: header button, login modal, session handling.
   Shared by the Studio and My Sketches pages. Exposes a global `Auth`. */

// Google login only accepts registered origins; use "localhost" instead of the raw IP while developing.
if (location.hostname === "127.0.0.1") location.replace(location.href.replace("//127.0.0.1", "//localhost"));

const Auth = (() => {
  let user = null, cfg = {google_client_id: ""}, gsiP = null, inited = false;
  let modal = null, slot = null, msgEl = null, errEl = null, devEl = null, cardEl = null;
  let waiters = [];

  const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt) e.textContent = txt; return e; };
  async function api(url, opts) {
    const r = await fetch(url, opts);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || "Request failed");
    return j;
  }

  // ---- Google Identity Services script ----
  function loadGsi() {
    if (gsiP) return gsiP;
    gsiP = new Promise((res, rej) => {
      if (window.google && google.accounts && google.accounts.id) return res();
      const s = document.createElement("script");
      s.src = "https://accounts.google.com/gsi/client"; s.async = true; s.defer = true;
      s.onload = res;
      s.onerror = () => { gsiP = null; rej(new Error("Could not load Google Sign-In. Check your internet connection.")); };
      document.head.append(s);
    });
    return gsiP;
  }
  function initGsi() {
    if (inited) return;
    google.accounts.id.initialize({client_id: cfg.google_client_id, callback: onCredential, auto_select: false, cancel_on_tap_outside: true});
    inited = true;
  }

  // ---- state ----
  function setUser(u) {
    user = u; renderSlot();
    document.dispatchEvent(new CustomEvent("auth:change", {detail: u}));
  }
  async function onCredential(resp) {
    errEl.textContent = "";
    try {
      const j = await api("/api/auth/google", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({credential: resp.credential})
      });
      setUser(j.user); closeModal(true);
    } catch (e) { errEl.textContent = e.message; }
  }
  async function logout() {
    try { await api("/api/auth/logout", {method: "POST"}); } catch {}
    if (window.google && google.accounts && google.accounts.id) google.accounts.id.disableAutoSelect();
    setUser(null);
  }

  // ---- login modal ----
  function buildModal() {
    modal = el("div", "auth-modal");
    modal.innerHTML =
      '<div class="auth-card" role="dialog" aria-modal="true" aria-labelledby="authTitle">' +
      '<button class="auth-x" aria-label="Close">\u2715</button>' +
      '<div class="auth-logo"><i></i>Graphite</div>' +
      '<h3 id="authTitle">Sign in to continue</h3>' +
      '<p class="auth-msg"></p>' +
      '<div class="auth-gbtn"></div>' +
      '<p class="auth-err"></p>' +
      '<small>We only use your name, email and photo to sign you in.</small>' +
      '<small class="auth-dev" style="display:none"></small></div>';
    document.body.append(modal);
    cardEl = modal.querySelector(".auth-card"); msgEl = modal.querySelector(".auth-msg");
    errEl = modal.querySelector(".auth-err"); devEl = modal.querySelector(".auth-dev");
    modal.querySelector(".auth-x").onclick = () => closeModal(false);
    modal.addEventListener("click", e => { if (e.target === modal) closeModal(false); });
    document.addEventListener("keydown", e => { if (e.key === "Escape" && modal.classList.contains("on")) closeModal(false); });
  }
  async function openModal(msg) {
    if (!modal) buildModal();
    msgEl.textContent = msg || "Log in with your Google account to create sketches.";
    errEl.textContent = "";
    if (location.hostname === "localhost") {           // developer hint, only on localhost
      devEl.textContent = "Dev note: add " + location.origin + " and http://localhost to \u201CAuthorized JavaScript origins\u201D in Google Cloud Console.";
      devEl.style.display = "block";
    }
    modal.classList.add("on");
    const m = window.Motion;
    if (m && !matchMedia("(prefers-reduced-motion: reduce)").matches)
      m.animate(cardEl, {opacity: [0, 1], y: [24, 0], scale: [0.96, 1]}, {duration: 0.35});
    if (!cfg.google_client_id) { errEl.textContent = "Google login is not set up on the server yet (GOOGLE_CLIENT_ID is missing)."; return; }
    try {
      await loadGsi(); initGsi();
      const box = modal.querySelector(".auth-gbtn"); box.replaceChildren();
      google.accounts.id.renderButton(box, {theme: "filled_black", size: "large", shape: "pill", text: "continue_with", logo_alignment: "left", width: 280});
    } catch (e) { errEl.textContent = e.message; }
  }
  function closeModal(ok) {
    if (modal) modal.classList.remove("on");
    const w = waiters; waiters = []; w.forEach(r => r(!!ok));
  }

  // ---- header button / user menu ----
  function renderSlot() {
    if (!slot) return;
    slot.replaceChildren();
    if (!user) {
      const b = el("button", "btn ghost auth-login", "Log in"); b.onclick = () => openModal(); slot.append(b); return;
    }
    const b = el("button", "auth-user"); b.setAttribute("aria-haspopup", "true");
    let av;
    if (user.picture) { av = new Image(); av.referrerPolicy = "no-referrer"; av.src = user.picture; av.alt = ""; av.className = "auth-av"; }
    else { av = el("span", "auth-av", (user.name || "?").charAt(0).toUpperCase()); }
    b.append(av, el("span", "auth-name", (user.name || "").split(" ")[0]));
    const menu = el("div", "auth-menu");
    const out = el("button", "btn ghost", "Log out"); out.onclick = logout;
    menu.append(el("b", "", user.name), el("span", "", user.email), out);
    menu.onclick = e => e.stopPropagation();
    b.onclick = e => { e.stopPropagation(); menu.classList.toggle("on"); };
    slot.append(b, menu);
  }
  document.addEventListener("click", () => { if (slot) { const m = slot.querySelector(".auth-menu.on"); if (m) m.classList.remove("on"); } });

  // ---- public API ----
  async function init() {
    const head = document.querySelector(".head-r");
    slot = el("div", "auth-slot");
    if (head) {                                         // sits right after "My Sketches", before the "Start sketching" button
      const cta = head.querySelector(".cta");
      cta ? head.insertBefore(slot, cta) : head.append(slot);
    }
    try { cfg = await api("/api/config"); } catch {}
    try { user = (await api("/api/me")).user; } catch {}
    renderSlot();
    document.dispatchEvent(new CustomEvent("auth:change", {detail: user}));
  }
  const ready = init();

  return {
    async require(msg) {                      // resolves true once logged in, false if the user closes the modal
      await ready;
      if (user) return true;
      return new Promise(res => { waiters.push(res); openModal(msg); });
    },
    expired() { setUser(null); openModal("Your session expired. Please log in again."); },
    open: openModal, logout,
    get user() { return user; }
  };
})();