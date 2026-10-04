// localStorage-backed sketch store (shared by Studio and My Sketches pages)
const KEY = "graphite.sketches.v1";
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);

// shrink to a JPEG data-URL so many sketches fit in the ~5 MB localStorage quota
function shrink(blob, max, q) {
  return new Promise((res, rej) => {
    const u = URL.createObjectURL(blob), i = new Image();
    i.onload = () => {
      const s = Math.min(1, max / Math.max(i.naturalWidth, i.naturalHeight));
      const c = document.createElement("canvas");
      c.width = Math.round(i.naturalWidth * s);
      c.height = Math.round(i.naturalHeight * s);
      c.getContext("2d").drawImage(i, 0, 0, c.width, c.height);
      URL.revokeObjectURL(u);
      res(c.toDataURL("image/jpeg", q));
    };
    i.onerror = () => { URL.revokeObjectURL(u); rej(new Error("decode")); };
    i.src = u;
  });
}

const Store = {
  all() { try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch { return []; } },
  _w(list) { localStorage.setItem(KEY, JSON.stringify(list)); },   // throws QuotaExceededError when full
  count() { return this.all().length; },
  usage() { return (localStorage.getItem(KEY) || "").length * 2; }, // approx bytes (UTF-16)
  remove(id) { this._w(this.all().filter(x => x.id !== id)); },
  clear() { localStorage.removeItem(KEY); },
  async saveBlob(blob, meta) {
    let err;
    for (const [max, q] of [[1200, 0.86], [800, 0.72]]) {          // second try = smaller file
      try {
        const item = {id: uid(), img: await shrink(blob, max, q), t: Date.now(), ...meta};
        const list = this.all(); list.unshift(item); this._w(list);
        return item;
      } catch (e) { err = e; }
    }
    throw err;
  }
};