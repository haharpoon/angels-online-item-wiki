/* Paper doll: atlas frames, tint, layer order, and a shareable loadout. */
(function () {
  const SPRITE_DIR = "pd/sprites/";
  const CATALOG = "pd/client_pd_preview.json";
  const SLOT_WIKI = { mount: "ride", mecha: "ride" };
  const SLOT_ORDER = ["head", "body", "hands", "feet", "back", "main", "off", "ride"];
  const DIR_LABEL = {
    back: "Back", "back-left": "Back left", left: "Left", "front-left": "Front left",
    front: "Front", "front-right": "Front right", right: "Right", "back-right": "Back right"
  };
  const GIF_DELAY = 320;
  const BG_MAX = 10 * 1024 * 1024;
  const GRADIENTS = {
    dusk: ["#2c2348", "#120e22", "#e4c36a"],
    grove: ["#1d4634", "#0e1c16", "#8fbf7a"],
    harbor: ["#1a3058", "#0c121c", "#7eb0d8"]
  };

  const dollCv = document.querySelector("#doll");
  const dollMeta = document.querySelector("#dollMeta");
  if (!dollCv) return;
  const ctx = dollCv.getContext("2d");

  let PD = null;
  const worn = {};
  const images = {};
  const tinted = {};
  const snap = {
    sex: "female", hair: 0, hairColor: 2, skinTone: 0,
    height: "average", direction: 4, phase: 0, background: "studio", crisp: true
  };
  let renderToken = 0;
  let lastTick = 0;
  let customImg = null;
  let customUrl = "";
  let applyingHash = false;

  function displayName(rec) {
    if (!rec) return "";
    if (rec.name && /[A-Za-z]/.test(rec.name)) return rec.name;
    const alias = (rec.aliases || []).find(n => /[A-Za-z]/.test(n));
    return alias || rec.name || "";
  }

  function wornId(slot) {
    const entry = worn[slot];
    if (!entry) return null;
    return typeof entry === "object" ? entry.id : entry;
  }

  function wornPlace(slot) {
    const entry = worn[slot];
    if (!entry || typeof entry !== "object") return "";
    return entry.placementId || "";
  }

  function pdFind(id) {
    if (!PD) return null;
    const n = Number(id);
    return PD.items.find(it => it.item_id === n || (it.itemIds || []).includes(n)) || null;
  }

  function spriteUrl(asset) {
    const name = (asset.url || "").split("/").pop();
    return SPRITE_DIR + name;
  }

  function loadImageElement(url) {
    return new Promise(resolve => {
      const img = new Image();
      img.decoding = "async";
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = url;
    });
  }

  function loadImage(url) {
    if (!images[url]) {
      if (url.startsWith("data:")) images[url] = loadImageElement(url);
      else images[url] = fetch(url).then(res => {
        if (!res.ok) throw new Error(String(res.status));
        return res.blob();
      }).then(blob => loadImageElement(URL.createObjectURL(blob))).catch(() => loadImageElement(url));
    }
    return images[url];
  }

  function recolor(img, color) {
    try {
      const c = document.createElement("canvas");
      c.width = img.naturalWidth || img.width;
      c.height = img.naturalHeight || img.height;
      const g = c.getContext("2d", { willReadFrequently: true });
      g.imageSmoothingEnabled = false;
      g.drawImage(img, 0, 0);
      const data = g.getImageData(0, 0, c.width, c.height);
      const px = data.data;
      const tol = (color.tolerance || 0) * (color.tolerance || 0);
      for (let i = 0; i < px.length; i += 4) {
        if (!px[i + 3]) continue;
        const r = px[i] - color.reference[0];
        const gg = px[i + 1] - color.reference[1];
        const b = px[i + 2] - color.reference[2];
        if (r * r + gg * gg + b * b > tol) continue;
        px[i] = Math.max(0, Math.min(255, px[i] + color.offsets[0]));
        px[i + 1] = Math.max(0, Math.min(255, px[i + 1] + color.offsets[1]));
        px[i + 2] = Math.max(0, Math.min(255, px[i + 2] + color.offsets[2]));
      }
      g.putImageData(data, 0, 0);
      return c;
    } catch (err) {
      return null;
    }
  }

  function tintDef(asset) {
    if (!asset) return null;
    if (asset.tint === "hair") return PD.customization.hairColors[snap.hairColor];
    if (asset.tint === "skin") return PD.customization.skinTones[snap.skinTone];
    return null;
  }

  async function tintedImage(key) {
    const asset = PD.sprites[key];
    if (!asset) return null;
    const color = tintDef(asset);
    const url = spriteUrl(asset);
    if (!color || !color.offsets || color.offsets.every(v => v === 0)) return loadImage(url);
    const cacheKey = key + ":" + asset.tint + ":" + (asset.tint === "hair" ? snap.hairColor : snap.skinTone);
    if (!tinted[cacheKey]) {
      tinted[cacheKey] = (async () => {
        const base = await loadImage(url);
        const maskUrl = (window.PD_TINT_MASKS || {})[key];
        // A sprite with no mask is not skin. Tinting the whole sheet recolours gold and leather.
        if (!maskUrl) return base;
        const source = await loadImage(maskUrl);
        const tintedLayer = source ? recolor(source, color) : null;
        if (!tintedLayer || !base) return base;
        const c = document.createElement("canvas");
        c.width = base.naturalWidth || base.width;
        c.height = base.naturalHeight || base.height;
        const g = c.getContext("2d");
        g.imageSmoothingEnabled = false;
        g.drawImage(base, 0, 0);
        g.drawImage(tintedLayer, 0, 0);
        return c;
      })();
    }
    return tinted[cacheKey];
  }

  function placementFor(rec, placementId) {
    const list = rec.placements || [];
    return list.find(p => p.id === placementId) || list[0] || { occupies: ["head"], layers: ["head"] };
  }

  function clearItem(id) {
    Object.keys(worn).forEach(slot => {
      if (wornId(slot) === id) delete worn[slot];
    });
  }

  function canonicalSlot(slot) {
    return SLOT_WIKI[slot] || slot;
  }

  function equipPlace(id, rec, place) {
    const slots = (place.occupies || ["head"]).map(canonicalSlot);
    if (rec.flags && rec.flags.twoHanded && slots.indexOf("off") < 0) slots.push("off");
    const doomed = new Set();
    slots.forEach(slot => {
      const other = wornId(slot);
      if (other) doomed.add(other);
    });
    ["main", "off"].forEach(slot => {
      if (slots.indexOf(slot) < 0) return;
      const partner = wornId(slot === "main" ? "off" : "main");
      const partnerRec = partner ? pdFind(partner) : null;
      if (partnerRec && partnerRec.flags && partnerRec.flags.twoHanded) doomed.add(partner);
    });
    doomed.forEach(clearItem);
    if (rec.flags && rec.flags.twoHanded) clearItem(wornId("off"));
    slots.forEach(slot => { worn[slot] = { id: id, placementId: place.id }; });
  }

  function shapeshiftWorn() {
    let found = null;
    SLOT_ORDER.forEach(slot => {
      if (found) return;
      const id = wornId(slot);
      if (!id) return;
      const rec = pdFind(id);
      if (rec && rec.flags && rec.flags.shapeshift) found = { rec: rec, slot: slot };
    });
    return found;
  }

  function layers() {
    const shift = shapeshiftWorn();
    if (shift) {
      // The sprite is the whole character. Leave out the dummy, hair, mount, and other gear.
      const pose = "standing";
      const place = placementFor(shift.rec, wornPlace(shift.slot));
      const comps = ((shift.rec.components || {})[snap.sex] || {})[pose] || {};
      const map = {};
      (place.layers || []).forEach(layer => {
        if (comps[layer]) map[layer] = comps[layer];
      });
      return { map: map, pose: pose, riderOffsetY: 0, layerMode: "ride" };
    }
    const rideId = wornId("ride");
    const ride = rideId ? pdFind(rideId) : null;
    const pose = ride ? "mounted" : "standing";
    const sex = PD.customization.sexes[snap.sex];
    const hair = sex.hairstyles[snap.hair] || sex.hairstyles[0];
    const map = { nude: sex.baseSprites[pose], hair: hair.sprites[pose] };
    let fullHead = false;
    const seen = new Set();
    SLOT_ORDER.forEach(slot => {
      const id = wornId(slot);
      if (!id || seen.has(slot + ":" + id + ":" + wornPlace(slot))) return;
      const rec = pdFind(id);
      if (!rec) return;
      seen.add(slot + ":" + id + ":" + wornPlace(slot));
      const place = placementFor(rec, wornPlace(slot));
      const comps = ((rec.components || {})[snap.sex] || {})[pose] || {};
      (place.layers || []).forEach(layer => {
        if (comps[layer]) map[layer] = comps[layer];
      });
      if (rec.flags && rec.flags.headCover === "full") fullHead = true;
    });
    const mainRec = wornId("main") ? pdFind(wornId("main")) : null;
    if (mainRec && mainRec.flags && mainRec.flags.twoHanded && wornId("off") !== wornId("main")) {
      delete map.off;
    }
    if (fullHead) delete map.hair;
    return {
      map,
      pose,
      riderOffsetY: ride && ride.ride ? ride.ride.riderOffsetY : 0,
      layerMode: (ride && ride.ride && ride.ride.layerMode) || "ride",
    };
  }

  function canvasSize() {
    const rect = dollCv.getBoundingClientRect();
    const ratio = Math.max(1, Math.min(3, window.devicePixelRatio || 1));
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));
    const bw = Math.round(width * ratio);
    const bh = Math.round(height * ratio);
    if (dollCv.width !== bw) dollCv.width = bw;
    if (dollCv.height !== bh) dollCv.height = bh;
    return { width, height, ratio };
  }

  function themeColor(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function drawCover(img, size) {
    const iw = img.naturalWidth || img.width;
    const ih = img.naturalHeight || img.height;
    if (!iw || !ih) return;
    const scale = Math.max(size.width / iw, size.height / ih);
    const w = iw * scale;
    const h = ih * scale;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(img, (size.width - w) / 2, (size.height - h) / 2, w, h);
  }

  function paintBackground(size) {
    ctx.setTransform(size.ratio, 0, 0, size.ratio, 0, 0);
    ctx.imageSmoothingEnabled = false;
    if (customImg) {
      ctx.fillStyle = themeColor("--bg", "#100c1c");
      ctx.fillRect(0, 0, size.width, size.height);
      drawCover(customImg, size);
      return;
    }
    if (snap.background === "plain") {
      const a = themeColor("--bg", "#100c1c");
      const b = themeColor("--panel", "#1b1530");
      const cell = 16;
      for (let y = 0; y < size.height; y += cell) {
        for (let x = 0; x < size.width; x += cell) {
          ctx.fillStyle = ((x / cell + y / cell) % 2) ? b : a;
          ctx.fillRect(x, y, cell, cell);
        }
      }
      return;
    }
    const grad = GRADIENTS[snap.background];
    if (grad) {
      const g = ctx.createLinearGradient(0, 0, 0, size.height);
      g.addColorStop(0, grad[0]);
      g.addColorStop(1, grad[1]);
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, size.width, size.height);
      ctx.fillStyle = grad[2];
      ctx.globalAlpha = 0.18;
      ctx.beginPath();
      ctx.ellipse(size.width / 2, size.height * 0.82, size.width * 0.28, 18, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      return;
    }
    ctx.fillStyle = themeColor("--bg", "#1a1d24");
    ctx.fillRect(0, 0, size.width, size.height);
    ctx.beginPath();
    for (let x = 0.5; x < size.width; x += 24) { ctx.moveTo(x, 0); ctx.lineTo(x, size.height); }
    for (let y = 0.5; y < size.height; y += 24) { ctx.moveTo(0, y); ctx.lineTo(size.width, y); }
    ctx.strokeStyle = themeColor("--line", "#2a3140");
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  function mountedBounds(preview, heightScale) {
    const bounds = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
    Object.keys(preview.map).forEach(layer => {
      const asset = PD.sprites[preview.map[layer]];
      if (!asset) return;
      const riderScale = layer === "ride" ? 1 : heightScale;
      const riderOffset = layer === "ride" ? 0 : -preview.riderOffsetY;
      (asset.frames || []).forEach(frame => {
        const left = -frame.anchorX;
        const right = left + frame.width;
        const top = (-frame.anchorY + riderOffset) * riderScale;
        const bottom = (-frame.anchorY + riderOffset + frame.height) * riderScale;
        bounds.minX = Math.min(bounds.minX, left, -right);
        bounds.maxX = Math.max(bounds.maxX, right, -left);
        bounds.minY = Math.min(bounds.minY, top);
        bounds.maxY = Math.max(bounds.maxY, bottom);
      });
    });
    return bounds;
  }

  function b64url(text) {
    return btoa(unescape(encodeURIComponent(text))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function fromB64url(text) {
    const pad = text.replace(/-/g, "+").replace(/_/g, "/");
    const padded = pad + "===".slice((pad.length + 3) % 4);
    return decodeURIComponent(escape(atob(padded)));
  }

  function payload() {
    const loadout = {};
    SLOT_ORDER.forEach(slot => {
      const id = wornId(slot);
      if (id) loadout[slot] = id;
    });
    const rideId = wornId("ride");
    if (rideId) {
      const rideRec = pdFind(rideId);
      const mode = rideRec && rideRec.ride && rideRec.ride.layerMode;
      loadout[mode === "robot" ? "mecha" : "mount"] = rideId;
    }
    return {
      v: 2,
      sex: snap.sex,
      hair: snap.hair,
      hairColor: snap.hairColor,
      skinTone: snap.skinTone,
      height: snap.height,
      direction: (PD.directions[snap.direction] || {}).id || "front",
      background: snap.background || "studio",
      loadout
    };
  }

  function wikiHref() {
    return "https://angelsonline.wiki/#pd-preview?pd=" + b64url(JSON.stringify(payload()));
  }

  function syncLink() {
    const a = document.querySelector("#dollWiki");
    if (a) a.href = wikiHref();
    if (!PD || applyingHash) return;
    const params = new URLSearchParams((location.hash || "").replace(/^#/, ""));
    params.set("pd", b64url(JSON.stringify(payload())));
    const next = "#" + params.toString();
    if (location.hash === next) return;
    history.replaceState(null, "", next);
  }

  function bagIcon(id) {
    if (typeof DATA === "undefined" || typeof FILES === "undefined") return "";
    const item = DATA.find(x => x.id === id);
    if (!item || item.icon == null) return "";
    const file = String(FILES[String(item.icon)] || "").toLowerCase().replace(/\.png$/i, "");
    const urls = [];
    if (item.icon) urls.push("icons/" + item.icon + ".png");
    if (file) urls.push("icons/" + file + ".png");
    if (!urls.length) return "";
    const next = urls.slice(1).join("|");
    return '<img src="' + urls[0] + '" alt="" data-next="' + next + '" onerror="pdIconFail(this)">';
  }

  window.pdIconFail = function (img) {
    const next = (img.dataset.next || "").split("|").filter(Boolean);
    if (!next.length) { img.remove(); return; }
    img.dataset.next = next.slice(1).join("|");
    img.src = next[0];
  };

  function esc(text) {
    return String(text).replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
  }

  function renderSlots() {
    const box = document.querySelector("#dollSlots");
    if (!box) return;
    box.innerHTML = SLOT_ORDER.map(slot => {
      const id = wornId(slot);
      const rec = id ? pdFind(id) : null;
      const label = rec ? (displayName(rec) || "Empty") : "Empty";
      const places = rec && rec.placements && rec.placements.length > 1 ? rec.placements : [];
      const current = wornPlace(slot);
      const hands = places.length
        ? '<div class="handToggle">' + places.map(p =>
          '<button type="button" data-hand="' + esc(p.id) + '" data-slot="' + slot + '"'
          + (p.id === current ? ' aria-pressed="true"' : "") + ">"
          + esc(p.id === "off" ? "Off hand" : p.id === "main" ? "Main hand" : p.id)
          + "</button>"
        ).join("") + "</div>"
        : "";
      return '<div class="slotCell"><button type="button" class="slotBtn" data-slot="' + slot + '"'
        + (id ? "" : " disabled") + ">"
        + (id ? bagIcon(id) : '<span class="slotPh">—</span>')
        + '<span><span class="slotName">' + slot + '</span><span class="slotItem">'
        + esc(label) + "</span></span></button>" + hands + "</div>";
    }).join("");
    box.querySelectorAll(".slotBtn[data-slot]").forEach(btn => {
      btn.onclick = () => {
        const id = wornId(btn.dataset.slot);
        if (!id) return;
        clearItem(id);
        dollMeta.textContent = "Removed " + btn.dataset.slot + ".";
        syncLink();
        paint();
        renderSlots();
      };
    });
    box.querySelectorAll(".handToggle button").forEach(btn => {
      btn.onclick = ev => {
        ev.stopPropagation();
        const slot = btn.dataset.slot;
        const id = wornId(slot);
        const rec = id ? pdFind(id) : null;
        if (!rec) return;
        const place = (rec.placements || []).find(p => p.id === btn.dataset.hand);
        if (!place) return;
        clearItem(id);
        equipPlace(id, rec, place);
        dollMeta.textContent = "Moved to " + btn.dataset.hand + ".";
        syncLink();
        paint();
        renderSlots();
      };
    });
  }

  function setPressed(root, attr, value) {
    if (!root) return;
    root.querySelectorAll("button").forEach(btn => {
      btn.setAttribute("aria-pressed", String(btn.getAttribute(attr) === String(value)));
    });
  }

  function fillHair() {
    const hairSel = document.querySelector("#dollHair");
    if (!hairSel || !PD) return;
    const styles = PD.customization.sexes[snap.sex].hairstyles || [];
    if (snap.hair >= styles.length) snap.hair = Math.max(0, styles.length - 1);
    if (snap.hair < 0) snap.hair = 0;
    hairSel.innerHTML = "";
    styles.forEach((style, i) => {
      const opt = document.createElement("option");
      opt.value = String(i);
      const number = style && style.number != null ? style.number : (i + 1);
      opt.textContent = "Hairstyle " + number;
      hairSel.appendChild(opt);
    });
    hairSel.value = String(snap.hair);
  }

  function fillControls() {
    fillHair();
    const hairBox = document.querySelector("#dollHairColors");
    if (hairBox && !hairBox.childElementCount) {
      PD.customization.hairColors.forEach((c, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "swatch";
        b.style.setProperty("--swatch", c.swatch || "#888");
        b.dataset.hair = i;
        b.title = "Hair color " + (i + 1);
        b.setAttribute("aria-label", b.title);
        b.onclick = () => {
          snap.hairColor = i;
          Object.keys(tinted).forEach(k => delete tinted[k]);
          setPressed(hairBox, "data-hair", i);
          paint();
          syncLink();
        };
        hairBox.appendChild(b);
      });
    }
    const skinBox = document.querySelector("#dollSkins");
    if (skinBox && !skinBox.childElementCount) {
      PD.customization.skinTones.forEach((c, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "swatch";
        b.style.setProperty("--swatch", c.swatch || "#888");
        b.dataset.skin = i;
        b.title = "Skin tone " + (i + 1);
        b.setAttribute("aria-label", b.title);
        b.onclick = () => {
          snap.skinTone = i;
          Object.keys(tinted).forEach(k => delete tinted[k]);
          setPressed(skinBox, "data-skin", i);
          paint();
          syncLink();
        };
        skinBox.appendChild(b);
      });
    }
    const bg = document.querySelector("#dollBg");
    if (bg) bg.value = snap.background;
    const crisp = document.querySelector("#dollCrisp");
    if (crisp) crisp.checked = !!snap.crisp;
    setPressed(document.querySelector("#dollSex"), "data-sex", snap.sex);
    setPressed(document.querySelector("#dollHairColors"), "data-hair", snap.hairColor);
    setPressed(document.querySelector("#dollSkins"), "data-skin", snap.skinTone);
    setPressed(document.querySelector("#dollHeight"), "data-h", snap.height);
    const dirEl = document.querySelector("#dollDir");
    if (dirEl && PD.directions[snap.direction]) {
      dirEl.textContent = DIR_LABEL[PD.directions[snap.direction].id] || "Front";
    }
    renderSlots();
  }

  function typingTarget(el) {
    if (!el || !el.tagName) return false;
    const tag = el.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
  }

  async function paint() {
    const token = ++renderToken;
    const size = canvasSize();
    paintBackground(size);
    if (!PD) return;
    const preview = layers();
    const dir = PD.directions[snap.direction] || PD.directions[4];
    const sourceId = PD.directions[dir.source].id;
    const orders = preview.pose === "standing"
      ? PD.layerOrders.standing
      : (PD.layerOrders.mounted[preview.layerMode] || PD.layerOrders.mounted.ride);
    const order = orders[sourceId] || orders.front || [];
    const visible = order.filter(layer => preview.map[layer]);
    const imgs = [];
    for (const layer of visible) imgs.push(await tintedImage(preview.map[layer]));
    if (token !== renderToken) return;
    paintBackground(size);
    ctx.imageSmoothingEnabled = false;
    const heightSetting = (PD.customization.heights || []).find(h => h.id === snap.height)
      || (PD.customization.heights || [])[1] || { scale: 1 };
    let scale = Math.min(size.width / 160, size.height / 145);
    let originX = size.width / 2;
    let originY = size.height * 0.76;
    let bounds = null;
    let pad = 0;
    if (preview.pose === "mounted") {
      bounds = mountedBounds(preview, heightSetting.scale);
      pad = Math.max(18, Math.min(size.width, size.height) * 0.06);
      const bw = Math.max(1, bounds.maxX - bounds.minX);
      const bh = Math.max(1, bounds.maxY - bounds.minY);
      scale = Math.min(scale, (size.width - pad * 2) / bw, (size.height - pad * 2) / bh);
    }
    // Integer scaling only. Crisp (default) snaps to whole *device* pixels so a
    // 1.5x/2.5x DPR screen still maps each sprite pixel to an exact pixel block;
    // otherwise snap to whole CSS pixels.
    if (snap.crisp) scale = Math.max(1, Math.floor(scale * size.ratio)) / size.ratio;
    else scale = Math.max(1, Math.floor(scale));
    originX = Math.round(originX * size.ratio) / size.ratio;
    originY = Math.round(originY * size.ratio) / size.ratio;
    if (bounds) {
      originX = size.width / 2 - ((bounds.minX + bounds.maxX) / 2) * scale;
      originY = size.height - pad - bounds.maxY * scale;
      originX = Math.round(originX * size.ratio) / size.ratio;
      originY = Math.round(originY * size.ratio) / size.ratio;
    }
    const frameIndex = snap.phase * 5 + dir.source;
    visible.forEach((layer, i) => {
      const asset = PD.sprites[preview.map[layer]];
      const img = imgs[i];
      if (!asset || !img) return;
      const frame = asset.frames[frameIndex] || asset.frames[dir.source];
      if (!frame) return;
      const riderLayer = preview.pose === "mounted" && layer !== "ride";
      ctx.save();
      ctx.translate(originX, originY);
      ctx.scale(scale * (dir.mirror ? -1 : 1), scale);
      if (riderLayer || preview.pose === "standing") ctx.scale(1, heightSetting.scale);
      ctx.drawImage(
        img, frame.x, frame.y, frame.width, frame.height,
        -frame.anchorX, -frame.anchorY - (riderLayer ? preview.riderOffsetY : 0),
        frame.width, frame.height
      );
      ctx.restore();
    });
    const dirEl = document.querySelector("#dollDir");
    if (dirEl) dirEl.textContent = DIR_LABEL[dir.id] || dir.id;
  }

  function applySex(sex) {
    snap.sex = sex;
    Object.keys(tinted).forEach(k => delete tinted[k]);
    fillHair();
    setPressed(document.querySelector("#dollSex"), "data-sex", snap.sex);
  }

  async function tryOnId(id, name) {
    if (!PD) {
      dollMeta.textContent = "Loading paper-doll sprites…";
      return;
    }
    const rec = pdFind(id);
    if (!rec) {
      dollMeta.textContent = (name || ("item " + id)) + " — no paper-doll sprite in the wiki catalog.";
      return;
    }
    const numeric = Number(id);
    const already = Object.keys(worn).some(slot => wornId(slot) === numeric || wornId(slot) === rec.item_id);
    if (already) {
      clearItem(numeric);
      clearItem(rec.item_id);
      (rec.itemIds || []).forEach(clearItem);
    } else {
      const place = (rec.placements && rec.placements[0]) || { id: "default", occupies: ["head"], layers: ["head"] };
      equipPlace(numeric, rec, place);
      if (rec.sexes && rec.sexes.length && rec.sexes.indexOf(snap.sex) < 0) applySex(rec.sexes[0]);
    }
    await paint();
    const pretty = displayName(rec) || name || id;
    const shift = shapeshiftWorn();
    let note = "";
    if (shift && rec.flags && rec.flags.shapeshift) {
      const drawn = Object.keys(layers().map).length;
      note = drawn
        ? " · full character, other layers hidden"
        : " · full character, no sprite for this sex";
    } else if (shift && !already) {
      note = " · hidden while a shapeshift is worn";
    }
    dollMeta.textContent = (already ? "Removed " : "Wearing ") + pretty + " · /item " + id + note;
    syncLink();
    renderSlots();
  }

  window.tryOn = function (item) {
    return tryOnId(item.id, item.name);
  };

  function readHash() {
    if (!PD) return false;
    const params = new URLSearchParams((location.hash || "").replace(/^#/, ""));
    const raw = params.get("pd");
    if (!raw) return false;
    let data;
    try { data = JSON.parse(fromB64url(raw)); }
    catch (err) { return false; }
    if (!data || data.v !== 2) return false;
    applyingHash = true;
    const sexes = PD.customization.sexes || {};
    if (data.sex && sexes[data.sex]) snap.sex = data.sex;
    const styles = (sexes[snap.sex] && sexes[snap.sex].hairstyles) || [];
    if (Number.isInteger(data.hair) && data.hair >= 0 && data.hair < styles.length) snap.hair = data.hair;
    else snap.hair = Math.min(snap.hair, Math.max(0, styles.length - 1));
    if (Number.isInteger(data.hairColor) && PD.customization.hairColors[data.hairColor]) snap.hairColor = data.hairColor;
    if (Number.isInteger(data.skinTone) && PD.customization.skinTones[data.skinTone]) snap.skinTone = data.skinTone;
    if ((PD.customization.heights || []).some(h => h.id === data.height)) snap.height = data.height;
    const dir = (PD.directions || []).findIndex(d => d.id === data.direction);
    if (dir >= 0) snap.direction = dir;
    const bg = document.querySelector("#dollBg");
    if (typeof data.background === "string" && (GRADIENTS[data.background] || data.background === "studio" || data.background === "plain")) {
      snap.background = data.background;
    }
    if (bg) bg.value = snap.background;
    Object.keys(worn).forEach(k => delete worn[k]);
    const loadout = data.loadout && typeof data.loadout === "object" ? data.loadout : {};
    function claim(slotKey) {
      if (!Object.prototype.hasOwnProperty.call(loadout, slotKey)) return;
      const slot = canonicalSlot(slotKey);
      if (SLOT_ORDER.indexOf(slot) < 0) return;
      const id = Number(loadout[slotKey]);
      const rec = pdFind(id);
      if (!rec) return;
      const place = (rec.placements || []).find(p => (p.occupies || []).map(canonicalSlot).includes(slot))
        || (rec.placements || [])[0];
      if (!place) return;
      const slots = (place.occupies || []).map(canonicalSlot);
      if (rec.flags && rec.flags.twoHanded && slots.indexOf("off") < 0) slots.push("off");
      if (slots.indexOf(slot) < 0) return;
      // A two-handed weapon already sitting in main+off keeps the off hand. Don't draw both.
      if (slots.some(s => {
        const cur = wornId(s);
        return cur && cur !== id;
      })) return;
      slots.forEach(s => { worn[s] = { id: id, placementId: place.id }; });
    }
    SLOT_ORDER.forEach(claim);
    if (!wornId("ride")) {
      if (Object.prototype.hasOwnProperty.call(loadout, "mecha")) claim("mecha");
      else if (Object.prototype.hasOwnProperty.call(loadout, "mount")) claim("mount");
    }
    Object.keys(tinted).forEach(k => delete tinted[k]);
    fillControls();
    applyingHash = false;
    paint();
    return true;
  }

  function copyLink() {
    const url = location.href;
    const done = () => { dollMeta.textContent = "Link copied."; };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done).catch(fallback);
      return;
    }
    fallback();
    function fallback() {
      const area = document.createElement("textarea");
      area.value = url;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy");
        done();
      } catch (err) {
        dollMeta.textContent = url;
      }
      area.remove();
    }
  }

  function savePng() {
    let blob;
    try { blob = dollCv.toDataURL("image/png"); }
    catch (err) { blob = ""; }
    if (!blob) {
      dollMeta.textContent = "Save PNG is blocked when this folder is opened as a file. The preview itself still draws.";
      return;
    }
    const a = document.createElement("a");
    a.href = blob;
    a.download = "paper-doll.png";
    a.click();
  }

  function bindUi() {
    dollCv.tabIndex = 0;
    dollCv.setAttribute("role", "img");
    if (!dollCv.getAttribute("aria-label")) dollCv.setAttribute("aria-label", "Paper doll preview");
    const left = document.querySelector("#dollLeft");
    const right = document.querySelector("#dollRight");
    if (left) left.onclick = () => {
      snap.direction = (snap.direction + PD.directions.length - 1) % PD.directions.length;
      paint(); syncLink();
    };
    if (right) right.onclick = () => {
      snap.direction = (snap.direction + 1) % PD.directions.length;
      paint(); syncLink();
    };
    document.querySelectorAll("#dollSex [data-sex]").forEach(btn => {
      btn.onclick = () => {
        applySex(btn.dataset.sex);
        paint(); syncLink(); renderSlots();
      };
    });
    const hairSel = document.querySelector("#dollHair");
    if (hairSel) hairSel.onchange = () => { snap.hair = Number(hairSel.value) || 0; paint(); syncLink(); };
    document.querySelectorAll("#dollHeight [data-h]").forEach(btn => {
      btn.onclick = () => {
        snap.height = btn.dataset.h;
        setPressed(document.querySelector("#dollHeight"), "data-h", snap.height);
        paint(); syncLink();
      };
    });
    const bg = document.querySelector("#dollBg");
    if (bg) bg.onchange = () => { snap.background = bg.value || "studio"; paint(); syncLink(); };
    const crisp = document.querySelector("#dollCrisp");
    if (crisp) crisp.onchange = () => { snap.crisp = crisp.checked; paint(); };
    const file = document.querySelector("#dollBgFile");
    if (file) file.onchange = () => {
      const picked = file.files && file.files[0];
      if (!picked) return;
      if (picked.size > BG_MAX) {
        dollMeta.textContent = "Background must be 10 MiB or smaller.";
        file.value = "";
        return;
      }
      if (!/^image\/(png|jpeg|webp)$/.test(picked.type)) {
        dollMeta.textContent = "Background must be a PNG, JPEG, or WebP.";
        file.value = "";
        return;
      }
      if (customUrl) URL.revokeObjectURL(customUrl);
      customUrl = URL.createObjectURL(picked);
      const img = new Image();
      img.onload = () => { customImg = img; paint(); };
      img.onerror = () => { dollMeta.textContent = "Could not read that image."; };
      img.src = customUrl;
      dollMeta.textContent = "Local background stays on this machine. It is not part of the link.";
    };
    const reset = document.querySelector("#dollReset");
    if (reset) reset.onclick = () => {
      Object.keys(worn).forEach(k => { delete worn[k]; });
      snap.sex = "female"; snap.hair = 0; snap.hairColor = 2; snap.skinTone = 0;
      snap.height = "average"; snap.direction = 4; snap.phase = 0; snap.background = "studio";
      Object.keys(tinted).forEach(k => delete tinted[k]);
      dollMeta.textContent = "Dummy reset. Click fashion, weapons or mounts.";
      fillControls();
      syncLink();
      paint();
    };
    const clear = document.querySelector("#dollClear");
    if (clear) clear.onclick = () => {
      Object.keys(worn).forEach(k => { delete worn[k]; });
      dollMeta.textContent = "Cleared equipped items.";
      renderSlots();
      syncLink();
      paint();
    };
    const copy = document.querySelector("#dollCopy");
    if (copy) copy.onclick = copyLink;
    const save = document.querySelector("#dollSave");
    if (save) save.onclick = savePng;
    const example = document.querySelector("#dollExample");
    if (example) example.onclick = async () => {
      Object.keys(worn).forEach(k => { delete worn[k]; });
      applySex("female");
      snap.hair = 0; snap.hairColor = 2; snap.skinTone = 0;
      snap.height = "average"; snap.direction = 4;
      Object.keys(tinted).forEach(k => delete tinted[k]);
      fillControls();
      for (const id of [8081, 87259, 87260, 1903]) {
        if (pdFind(id)) await tryOnId(id);
      }
      dollMeta.textContent = "Wiki example: 1st hat + 2026 Aurora set + Angel Baby Pig.";
      syncLink();
    };
    dollCv.addEventListener("pointerdown", ev => {
      dollCv._sx = ev.clientX;
      dollCv.focus();
      try { dollCv.setPointerCapture(ev.pointerId); } catch (err) { /* older browsers */ }
    });
    dollCv.addEventListener("pointerup", ev => {
      const dx = ev.clientX - (dollCv._sx || ev.clientX);
      try { dollCv.releasePointerCapture(ev.pointerId); } catch (err) { /* not captured */ }
      if (Math.abs(dx) < 24) return;
      snap.direction = (snap.direction + (dx < 0 ? 1 : PD.directions.length - 1)) % PD.directions.length;
      paint(); syncLink();
    });
    window.addEventListener("resize", () => paint());
    window.addEventListener("keydown", ev => {
      if (!PD) return;
      if (typingTarget(ev.target)) return;
      if (ev.target !== dollCv && !dollCv.contains(ev.target)) return;
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      ev.preventDefault();
      snap.direction = (snap.direction + (ev.key === "ArrowRight" ? 1 : PD.directions.length - 1)) % PD.directions.length;
      paint(); syncLink();
    });
    window.addEventListener("hashchange", () => { readHash(); });
    function tick(now) {
      if (!PD || document.hidden) { requestAnimationFrame(tick); return; }
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (!reduce && now - lastTick > GIF_DELAY) {
        snap.phase = (snap.phase + 1) % 3;
        lastTick = now;
        paint();
      }
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  function boot(data) {
    PD = data;
    dollMeta.textContent = "Click a row to dress the dummy.";
    fillControls();
    bindUi();
    if (!readHash()) {
      syncLink();
      return paint();
    }
    syncLink();
  }
  if (window.PD_CATALOG) {
    boot(window.PD_CATALOG);
  } else {
    fetch(CATALOG).then(r => r.json()).then(boot).catch(() => {
      dollMeta.textContent = "Paper-doll catalog missing. Keep the pd folder next to this HTML (docs/pd in a GitHub download).";
      paintBackground(canvasSize());
    });
  }
})();
