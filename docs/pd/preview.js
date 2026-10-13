/* Same catalog, atlases, tint, anchors, and paint math as angelsonline.wiki/pd-preview. */
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

  const dollCv = document.querySelector("#doll");
  const dollMeta = document.querySelector("#dollMeta");
  if (!dollCv) return;
  const ctx = dollCv.getContext("2d");

  let PD = null;
  const worn = {};
  const images = {};
  const tinted = {};
  const snap = { sex: "female", hair: 0, hairColor: 2, skinTone: 0, height: "average", direction: 4, phase: 0 };
  let renderToken = 0;
  let lastTick = 0;

  function pdFind(id) {
    if (!PD) return null;
    const n = Number(id);
    return PD.items.find(it => it.item_id === n || (it.itemIds || []).includes(n)) || null;
  }

  function spriteUrl(asset) {
    const name = (asset.url || "").split("/").pop();
    return SPRITE_DIR + name;
  }

  function loadImage(url) {
    if (!images[url]) {
      images[url] = new Promise(resolve => {
        const img = new Image();
        img.decoding = "async";
        img.onload = () => resolve(img);
        img.onerror = () => resolve(null);
        img.src = url;
      });
    }
    return images[url];
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
      tinted[cacheKey] = loadImage(url).then(img => {
        if (!img) return null;
        const c = document.createElement("canvas");
        c.width = img.naturalWidth;
        c.height = img.naturalHeight;
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
      });
    }
    return tinted[cacheKey];
  }

  function layers() {
    const ride = worn.ride ? pdFind(worn.ride) : null;
    const pose = ride ? "mounted" : "standing";
    const sex = PD.customization.sexes[snap.sex];
    const hair = sex.hairstyles[snap.hair] || sex.hairstyles[0];
    const map = { nude: sex.baseSprites[pose], hair: hair.sprites[pose] };
    let fullHead = false;
    Object.keys(worn).forEach(slot => {
      const rec = worn[slot] ? pdFind(worn[slot]) : null;
      if (!rec) return;
      const place = rec.placements[0] || {};
      const comps = ((rec.components || {})[snap.sex] || {})[pose] || {};
      (place.layers || []).forEach(layer => {
        if (comps[layer]) map[layer] = comps[layer];
      });
      if (rec.flags && rec.flags.headCover === "full") fullHead = true;
    });
    if (fullHead) delete map.hair;
    return {
      map,
      pose,
      riderOffsetY: ride && ride.ride ? ride.ride.riderOffsetY : 0,
      layerMode: ride && ride.ride ? ride.ride.layerMode : "ride",
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

  function studio(size) {
    ctx.setTransform(size.ratio, 0, 0, size.ratio, 0, 0);
    ctx.fillStyle = "#1a1d24";
    ctx.fillRect(0, 0, size.width, size.height);
    ctx.beginPath();
    for (let x = 0.5; x < size.width; x += 24) { ctx.moveTo(x, 0); ctx.lineTo(x, size.height); }
    for (let y = 0.5; y < size.height; y += 24) { ctx.moveTo(0, y); ctx.lineTo(size.width, y); }
    ctx.strokeStyle = "#2a3140";
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

  function wikiHref() {
    const loadout = {};
    Object.keys(worn).forEach(k => { if (worn[k]) loadout[k] = worn[k]; });
    const payload = {
      v: 2, sex: snap.sex, hair: snap.hair, hairColor: snap.hairColor,
      skinTone: snap.skinTone, height: snap.height,
      direction: (PD.directions[snap.direction] || {}).id || "front",
      background: "studio", loadout
    };
    const b64 = btoa(unescape(encodeURIComponent(JSON.stringify(payload))))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
    return "https://angelsonline.wiki/#pd-preview?pd=" + b64;
  }

  function syncLink() {
    const a = document.querySelector("#dollWiki");
    if (a) a.href = wikiHref();
  }

  function bagIcon(id) {
    if (typeof DATA === "undefined" || typeof FILES === "undefined") return "";
    const item = DATA.find(x => x.id === id);
    if (!item || item.icon == null) return "";
    const src = FILES[String(item.icon)];
    return src ? '<img src="icons/' + src + '" alt="">' : "";
  }

  function renderSlots() {
    const box = document.querySelector("#dollSlots");
    if (!box) return;
    box.innerHTML = SLOT_ORDER.map(slot => {
      const id = worn[slot];
      const rec = id ? pdFind(id) : null;
      const label = rec ? (rec.aliases && rec.aliases.find(n => /[A-Za-z]/.test(n)) || rec.name) : "Empty";
      return '<button type="button" class="slotBtn" data-slot="' + slot + '"' + (id ? "" : " disabled") + ">"
        + (id ? bagIcon(id) : '<span class="slotPh">—</span>')
        + '<span><span class="slotName">' + slot + '</span><span class="slotItem">'
        + String(label).replace(/[<>&]/g, "") + "</span></span></button>";
    }).join("");
    box.querySelectorAll(".slotBtn[data-slot]").forEach(btn => {
      btn.onclick = () => {
        const slot = btn.dataset.slot;
        if (!worn[slot]) return;
        delete worn[slot];
        dollMeta.textContent = "Removed " + slot + ".";
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

  function fillControls() {
    const hairSel = document.querySelector("#dollHair");
    if (hairSel && !hairSel.options.length) {
      const styles = PD.customization.sexes[snap.sex].hairstyles;
      styles.forEach((_, i) => {
        const opt = document.createElement("option");
        opt.value = i;
        opt.textContent = "Hairstyle " + (i + 1);
        hairSel.appendChild(opt);
      });
    }
    if (hairSel) hairSel.value = String(snap.hair);
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
        b.onclick = () => { snap.hairColor = i; Object.keys(tinted).forEach(k => delete tinted[k]); setPressed(hairBox, "data-hair", i); paint(); syncLink(); };
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
        b.onclick = () => { snap.skinTone = i; Object.keys(tinted).forEach(k => delete tinted[k]); setPressed(skinBox, "data-skin", i); paint(); syncLink(); };
        skinBox.appendChild(b);
      });
    }
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

  async function paint() {
    const token = ++renderToken;
    const size = canvasSize();
    if (!PD) { studio(size); return; }
    const preview = layers();
    const dir = PD.directions[snap.direction] || PD.directions[4];
    const sourceId = PD.directions[dir.source].id;
    const order = preview.pose === "standing"
      ? PD.layerOrders.standing[sourceId]
      : PD.layerOrders.mounted[preview.layerMode][sourceId];
    const visible = order.filter(layer => preview.map[layer]);
    const imgs = [];
    for (const layer of visible) imgs.push(await tintedImage(preview.map[layer]));
    if (token !== renderToken) return;
    studio(size);
    ctx.imageSmoothingEnabled = false;
    const heightSetting = (PD.customization.heights || []).find(h => h.id === snap.height)
      || (PD.customization.heights || [])[1] || { scale: 1 };
    let scale = Math.min(size.width / 160, size.height / 145);
    let originX = size.width / 2;
    let originY = size.height * 0.76;
    if (preview.pose === "mounted") {
      const bounds = mountedBounds(preview, heightSetting.scale);
      const pad = Math.max(18, Math.min(size.width, size.height) * 0.06);
      const bw = Math.max(1, bounds.maxX - bounds.minX);
      const bh = Math.max(1, bounds.maxY - bounds.minY);
      scale = Math.min(scale, (size.width - pad * 2) / bw, (size.height - pad * 2) / bh);
      originX = size.width / 2 - ((bounds.minX + bounds.maxX) / 2) * scale;
      originY = size.height - pad - bounds.maxY * scale;
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
    const place = rec.placements[0] || {};
    const slots = place.occupies || ["head"];
    const wikiSlots = slots.map(s => SLOT_WIKI[s] || s);
    const already = wikiSlots.every(s => worn[s] === id);
    wikiSlots.forEach(s => { worn[s] = already ? null : id; });
    wikiSlots.forEach(s => { if (!worn[s]) delete worn[s]; });
    if (!already && rec.sexes && rec.sexes.length && rec.sexes.indexOf(snap.sex) < 0) {
      snap.sex = rec.sexes[0];
      Object.keys(tinted).forEach(k => delete tinted[k]);
      setPressed(document.querySelector("#dollSex"), "data-sex", snap.sex);
    }
    await paint();
    const pretty = (rec.aliases && rec.aliases.find(n => /[A-Za-z]/.test(n))) || rec.name || name || id;
    dollMeta.textContent = (already ? "Removed " : "Wearing ") + pretty + " · /item " + id;
    syncLink();
    renderSlots();
  }

  window.tryOn = function (item) {
    return tryOnId(item.id, item.name);
  };

  function bindUi() {
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
        snap.sex = btn.dataset.sex;
        Object.keys(tinted).forEach(k => delete tinted[k]);
        setPressed(document.querySelector("#dollSex"), "data-sex", snap.sex);
        paint(); syncLink(); renderSlots();
      };
    });
    const hairSel = document.querySelector("#dollHair");
    if (hairSel) hairSel.onchange = () => { snap.hair = Number(hairSel.value); paint(); syncLink(); };
    document.querySelectorAll("#dollHeight [data-h]").forEach(btn => {
      btn.onclick = () => {
        snap.height = btn.dataset.h;
        setPressed(document.querySelector("#dollHeight"), "data-h", snap.height);
        paint(); syncLink();
      };
    });
    const reset = document.querySelector("#dollReset");
    if (reset) reset.onclick = () => {
      Object.keys(worn).forEach(k => { delete worn[k]; });
      snap.sex = "female"; snap.hair = 0; snap.hairColor = 2; snap.skinTone = 0;
      snap.height = "average"; snap.direction = 4; snap.phase = 0;
      Object.keys(tinted).forEach(k => delete tinted[k]);
      dollMeta.textContent = "Dummy reset. Click fashion, weapons or mounts.";
      fillControls();
      syncLink();
      paint();
    };
    const example = document.querySelector("#dollExample");
    if (example) example.onclick = async () => {
      Object.keys(worn).forEach(k => { delete worn[k]; });
      snap.sex = "female"; snap.hair = 0; snap.hairColor = 2; snap.skinTone = 0;
      snap.height = "average"; snap.direction = 4;
      Object.keys(tinted).forEach(k => delete tinted[k]);
      fillControls();
      for (const id of [8081, 87259, 87260, 1903]) {
        if (pdFind(id)) await tryOnId(id);
      }
      dollMeta.textContent = "Wiki example: 1st hat + 2026 Aurora set + Angel Baby Pig.";
      syncLink();
    };
    dollCv.addEventListener("pointerdown", ev => { dollCv._sx = ev.clientX; });
    dollCv.addEventListener("pointerup", ev => {
      const dx = ev.clientX - (dollCv._sx || ev.clientX);
      if (Math.abs(dx) < 24) return;
      snap.direction = (snap.direction + (dx < 0 ? 1 : PD.directions.length - 1)) % PD.directions.length;
      paint(); syncLink();
    });
    window.addEventListener("resize", () => paint());
    window.addEventListener("keydown", ev => {
      if (!PD) return;
      if (ev.key === "ArrowLeft") { snap.direction = (snap.direction + PD.directions.length - 1) % PD.directions.length; paint(); syncLink(); }
      if (ev.key === "ArrowRight") { snap.direction = (snap.direction + 1) % PD.directions.length; paint(); syncLink(); }
    });
    function tick(now) {
      if (!PD) { requestAnimationFrame(tick); return; }
      if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches && now - lastTick > GIF_DELAY) {
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
    dollMeta.textContent = "Click a row. Same sprite sheets as angelsonline.wiki.";
    fillControls();
    bindUi();
    syncLink();
    return paint();
  }
  if (window.PD_CATALOG) {
    boot(window.PD_CATALOG);
  } else {
    fetch(CATALOG).then(r => r.json()).then(boot).catch(() => {
      dollMeta.textContent = "Paper-doll catalog missing. Keep the pd folder next to this HTML (docs/pd in a GitHub download).";
      studio(canvasSize());
    });
  }
})();
