// Home page truck showroom (templates/home/index.html, static/home/home.css).
// The carriers stand in a 3D row: drag, wheel/trackpad, swipe or arrow keys move it with momentum, and the truck at
// the centre is the active carrier. Clicking a side truck flies it to the centre; clicking the centre truck opens its
// detail view, where the same truck lands in the full photo and the camera moves between its facets. A WebGL radial
// noise wave carries each carrier's colour through the background. Data comes from the page's JSON block.
(() => {
  "use strict";

  const hero = document.querySelector("[data-hero]");
  const dataBlock = document.getElementById("fleet-data");
  if (!hero || !dataBlock) return; // no carriers: the empty state needs no script

  const data = JSON.parse(dataBlock.textContent);
  const carriers = data.carriers;
  const N = carriers.length;
  const LOOP = N >= 3;
  const TRUCK_W = data.truck.width;
  const TRUCK_H = data.truck.height;
  const [ORIGIN_X, ORIGIN_Y] = data.truck.origin; // the cut-out's place inside the scene photo
  const GROUND = 17; // px between the bottom of the cut-out and where the wheels touch the floor
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const body = document.body;

  const $ = (selector, root = document) => root.querySelector(selector);
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const mod = (v, n) => ((v % n) + n) % n;
  const pad = (n) => String(n).padStart(2, "0");
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

  const fleet = $("[data-fleet]");
  const parts = Array.from(fleet.children, (el) => ({
    el,
    art: $(".truck-art", el),
    shade: $(".truck-shade", el),
    hit: $(".truck-hit", el),
    off: false,
  }));
  const topbar = $(".topbar");
  const ui = {
    name: $("[data-name]"),
    line: $("[data-line]"),
    counter: $("[data-counter]"),
    word: $("[data-word]"),
    live: $("[data-live]"),
  };

  /* ---------- Markings: shrink each text until it fits its box (measured before any transform) ---------- */

  // Start large and shrink, so short names fill the space; the server's sizes only serve pages without script.
  function fit(el, largest, fits) {
    let size = largest;
    el.style.setProperty("--fs", String(size));
    for (let i = 0; i < 40 && !fits(size); i++) {
      size *= 0.95;
      el.style.setProperty("--fs", size.toFixed(1));
    }
  }

  for (const { art } of parts) {
    const mark = $(".livery-mark", art);
    const name = $(".livery-name", mark);
    const rate = $(".livery-rate", mark);
    // The name: at most two lines (line-height 0.96), no word wider than the zone, room left for the rate line.
    fit(name, 104, (size) => {
      const room = mark.clientHeight - rate.offsetHeight - 16;
      return name.scrollWidth <= name.clientWidth + 1 && name.offsetHeight <= Math.min(size * 0.96 * 2 + 2, room);
    });
    const size = $(".livery-size-value", art);
    fit(size, 30, () => size.scrollWidth <= size.parentElement.clientWidth + 1);
    // Cargo badges: one column above the diamond, wrapping inside a badge before shrinking.
    const cargo = $(".livery-cargo", art);
    const inner = $(".cargo-inner", cargo);
    const badges = inner.querySelectorAll(".cargo-badge");
    fit(inner, 18, () =>
      inner.offsetHeight <= cargo.clientHeight + 1 && [...badges].every((b) => b.scrollWidth <= b.clientWidth + 1),
    );
    $(".door", art)
      .querySelectorAll("span")
      .forEach((line, i) => fit(line, i ? 32 : 60, () => line.scrollWidth <= line.clientWidth + 1));
  }

  /* ---------- Layout ---------- */

  const layout = { W: 0, k: 0, floor: 0, mobile: false, perspective: 2000 };

  function measure() {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    layout.mobile = vw < 760;
    const byWidth = layout.mobile ? vw * 0.96 : clamp(vw * 0.52, 380, 980);
    const byHeight = vh * (layout.mobile ? 0.3 : 0.48) * (TRUCK_W / TRUCK_H);
    layout.W = Math.min(byWidth, byHeight);
    layout.k = layout.W / TRUCK_W;
    layout.floor = vh * (layout.mobile ? 0.67 : 0.71);
    layout.perspective = Math.max(1400, layout.W * 2.3);
    fleet.style.setProperty("--k", layout.k.toFixed(4));
    body.style.setProperty("--floor", `${layout.floor.toFixed(1)}px`);
  }

  // Where the centre truck's cut-out sits on screen at rest (its top-left corner and scale).
  function heroRect() {
    return {
      x: window.innerWidth / 2 - layout.W / 2,
      y: layout.floor - TRUCK_H * layout.k + GROUND * layout.k,
      s: layout.k,
    };
  }

  /* ---------- Row state and physics ---------- */

  const S = { pos: 0, vel: 0, target: 0, mode: "idle", flyer: -1, lift: 0, flight: null, raf: 0, last: 0, active: -1 };
  const LIMIT = LOOP ? Math.min(2.6, N / 2 - 0.25) : 2.6; // trucks further out are hidden (and wrap unseen)

  const wrap = (d) => (LOOP ? mod(d + N / 2, N) - N / 2 : d);
  const nearest = () => (LOOP ? Math.round(S.pos) : clamp(Math.round(S.pos), 0, N - 1));
  const indexAt = (pos) => (LOOP ? mod(Math.round(pos), N) : clamp(Math.round(pos), 0, N - 1));

  function render() {
    const { W, perspective } = layout;
    for (let i = 0; i < N; i++) {
      const p = parts[i];
      const d = wrap(i - S.pos);
      const ad = Math.abs(d);
      const off = ad > LIMIT;
      if (off !== p.off) {
        p.off = off;
        p.el.classList.toggle("is-off", off);
      }
      if (off) continue;
      const side = Math.sign(d);
      let x = side * W * 1.5 * (1 - Math.exp(-ad * 0.6));
      let y = 0;
      let z = -W * (0.6 * ad + 0.07 * ad * ad);
      let turn = side * 30 * (1 - Math.exp(-ad * 0.75));
      let shade = 0.9 * (1 - Math.exp(-ad * 0.85));
      if (i === S.flyer && S.lift > 0) {
        // The clicked truck pulls forward out of the row on its way to the centre.
        const lift = S.lift;
        z += lift * W * 0.42;
        y -= lift * W * 0.045;
        turn *= 1 - lift;
        shade *= 1 - lift * 0.9;
      }
      p.el.style.transform =
        `perspective(${perspective.toFixed(0)}px) translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, ${z.toFixed(2)}px) ` +
        `rotateY(${turn.toFixed(3)}deg)`;
      p.el.style.opacity = clamp((LIMIT - ad) / 0.45, 0, 1).toFixed(3);
      p.el.style.zIndex = String(i === S.flyer && S.lift > 0.04 ? 300 : 200 - Math.round(ad * 20));
      p.shade.style.opacity = shade.toFixed(3);
    }
    setActive(indexAt(S.pos));
  }

  function kick() {
    if (S.raf) return;
    S.last = performance.now();
    S.raf = requestAnimationFrame(tick);
  }

  function tick(now) {
    const dt = Math.min(0.1, (now - S.last) / 1000); // slow frames still move at real speed; a long pause does not jump
    S.last = now;
    if (S.mode === "spring") {
      const stiffness = 160;
      const damping = 2 * Math.sqrt(stiffness) * 0.9;
      for (let left = dt; left > 0; left -= 1 / 120) {
        const h = Math.min(left, 1 / 120); // fixed small steps keep the spring stable at any frame rate
        S.vel += (stiffness * (S.target - S.pos) - damping * S.vel) * h;
        S.pos += S.vel * h;
      }
      if (Math.abs(S.target - S.pos) < 0.0005 && Math.abs(S.vel) < 0.003) {
        S.pos = S.target;
        S.vel = 0;
        S.mode = "idle";
        settled();
      }
    } else if (S.mode === "flight") {
      const f = S.flight;
      const t = clamp((now - f.start) / f.duration, 0, 1);
      S.pos = f.from + (f.to - f.from) * easeInOut(t);
      S.lift = Math.sin(Math.PI * t) ** 1.4;
      if (t >= 1) {
        S.pos = S.target = f.to;
        S.lift = 0;
        S.flyer = -1;
        S.mode = "idle";
        settled();
      }
    }
    if (S.mode !== "flight" && S.lift > 0) {
      S.lift = Math.max(0, S.lift - dt * 4); // an interrupted flight sinks back into the row
      if (!S.lift) S.flyer = -1;
    }
    render();
    S.raf = S.mode === "idle" && !S.lift ? 0 : requestAnimationFrame(tick);
  }

  function springTo(target, velocity = S.vel) {
    S.target = LOOP ? target : clamp(target, 0, N - 1);
    if (S.mode === "flight") S.mode = "spring";
    if (reduced.matches) {
      S.pos = S.target;
      S.vel = 0;
      S.mode = "idle";
      S.lift = 0;
      S.flyer = -1;
      render();
      settled();
      return;
    }
    S.vel = velocity;
    S.mode = "spring";
    kick();
  }

  function step(delta) {
    if (D.open || D.busy) return;
    const base = S.mode === "spring" ? Math.round(S.target) : nearest();
    springTo(base + delta);
  }

  function flyTo(i) {
    const from = nearest();
    const delta = LOOP ? wrap(i - mod(from, N)) : i - from;
    if (!delta) return springTo(from);
    if (reduced.matches) return springTo(from + delta);
    S.mode = "flight";
    S.flyer = i;
    S.vel = 0;
    S.target = from + delta;
    S.flight = { from: S.pos, to: from + delta, start: performance.now(), duration: 950 + 170 * Math.abs(delta) };
    kick();
  }

  // Stop where we are and stand on the nearest truck (before opening the detail view).
  function settleNow() {
    if (S.mode === "idle" && !S.lift) return;
    S.pos = S.target = nearest();
    S.vel = 0;
    S.mode = "idle";
    S.lift = 0;
    S.flyer = -1;
    render();
  }

  /* ---------- Active carrier ---------- */

  let swept = -1;

  function setActive(i) {
    if (i === S.active) return;
    S.active = i;
    const c = carriers[i];
    swap(ui.name, c.name);
    swap(ui.line, c.line);
    swapWord(c.name);
    ui.counter.textContent = `${pad(i + 1)} / ${pad(N)}`;
    body.style.setProperty("--accent", c.accent);
    const focused = document.activeElement?.classList.contains("truck-hit");
    parts.forEach((p, j) => {
      p.hit.tabIndex = j === i ? 0 : -1;
      p.el.classList.toggle("is-active", j === i);
    });
    if (focused) parts[i].hit.focus({ preventScroll: true });
    try {
      history.replaceState(null, "", `/${c.slug}`); // /a-logistics: a reload or a shared link opens the same carrier
    } catch {
      /* file:// or sandboxed: the hash is a convenience */
    }
    noise.to(c.accent);
  }

  function settled() {
    const c = carriers[S.active];
    ui.live.textContent = `${c.name}, ${S.active + 1} / ${N}`;
    if (swept !== S.active && !reduced.matches) {
      const el = parts[S.active].el;
      el.classList.remove("is-sweep");
      void el.offsetWidth; // restart the animation
      el.classList.add("is-sweep");
    }
    swept = S.active;
  }

  // The giant outline name: animate a child, so the parent's opacity (hidden in the detail view) stays in CSS.
  function swapWord(text) {
    if (ui.word.textContent === text) return;
    const span = document.createElement("span");
    span.textContent = text;
    if (!reduced.matches) span.className = "swap-in";
    ui.word.replaceChildren(span);
  }

  function swap(el, text) {
    if (el.textContent === text) return;
    el.textContent = text;
    if (reduced.matches) return;
    el.classList.remove("swap-in");
    void el.offsetWidth;
    el.classList.add("swap-in");
  }

  /* ---------- Input: drag, click, wheel, keys ---------- */

  const drag = { id: null, x0: 0, pos0: 0, moved: false, samples: [], stopped: false, suppress: false };

  fleet.addEventListener("pointerdown", (e) => {
    if (D.open || D.busy || e.button !== 0) return;
    drag.id = e.pointerId;
    drag.x0 = e.clientX;
    drag.pos0 = S.pos;
    drag.moved = false;
    drag.stopped = S.mode !== "idle"; // grabbing a moving row stops it
    drag.samples = [[e.timeStamp, S.pos]];
    if (S.mode !== "idle") {
      S.mode = "drag";
      S.vel = 0;
      kick();
    }
  });

  window.addEventListener("pointermove", (e) => {
    if (e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x0;
    if (!drag.moved) {
      if (Math.abs(dx) < 6) return;
      drag.moved = true;
      drag.x0 = e.clientX;
      fleet.setPointerCapture(e.pointerId);
      fleet.classList.add("is-dragging");
      S.mode = "drag";
      S.vel = 0;
      S.flyer = -1;
      S.lift = 0;
      kick();
      return;
    }
    let pos = drag.pos0 - dx / (layout.W * 0.62);
    if (!LOOP) pos = pos < 0 ? pos * 0.35 : pos > N - 1 ? N - 1 + (pos - N + 1) * 0.35 : pos; // rubber band
    S.pos = pos;
    drag.samples.push([e.timeStamp, pos]);
    while (drag.samples.length > 2 && e.timeStamp - drag.samples[0][0] > 100) drag.samples.shift();
  });

  function endDrag(e) {
    if (e.pointerId !== drag.id) return;
    drag.id = null;
    fleet.classList.remove("is-dragging");
    if (!drag.moved) {
      if (drag.stopped) springTo(nearest(), 0);
      return;
    }
    drag.suppress = true; // the click that follows a drag is not a click
    setTimeout(() => (drag.suppress = false), 0);
    const [t0, p0] = drag.samples[0];
    const [t1, p1] = drag.samples[drag.samples.length - 1];
    const velocity = t1 > t0 ? clamp((p1 - p0) / ((t1 - t0) / 1000), -14, 14) : 0;
    const projected = Math.round(S.pos + velocity * 0.2);
    springTo(clamp(projected, Math.round(S.pos) - 4, Math.round(S.pos) + 4), velocity);
  }
  window.addEventListener("pointerup", endDrag);
  window.addEventListener("pointercancel", endDrag);

  parts.forEach((p, i) =>
    p.hit.addEventListener("click", () => {
      if (drag.suppress || D.open || D.busy) return;
      if (i === S.active && Math.abs(S.pos - nearest()) < 0.08) openDetail();
      else flyTo(i);
    }),
  );

  // Wheel and trackpad: the row follows the scroll, then settles on a truck (leaning the way it was going).
  const WHEEL_PX = 280;
  const wheel = { timer: 0, dir: 0, size: 0, lock: null };
  window.addEventListener(
    "wheel",
    (e) => {
      if (D.open || D.busy || e.ctrlKey) return;
      e.preventDefault();
      let delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      if (e.deltaMode === 1) delta *= 32;
      else if (e.deltaMode === 2) delta *= window.innerHeight;
      if (!delta) return;
      const dir = Math.sign(delta);
      const size = Math.abs(delta);
      const now = e.timeStamp;
      // macOS keeps sending a fading tail after the fingers lift; after a settle, ignore it until it grows or turns.
      const lock = wheel.lock;
      if (lock && dir === lock.dir && size <= lock.size * 1.15 && now - lock.time < 220) {
        lock.size = size;
        lock.time = now;
        return;
      }
      wheel.lock = null;
      if (S.mode !== "spring") {
        S.target = S.pos;
        S.flyer = -1;
      }
      S.target = clamp(S.target + delta / WHEEL_PX, S.pos - 2.5, S.pos + 2.5);
      if (!LOOP) S.target = clamp(S.target, -0.3, N - 0.7);
      S.mode = "spring";
      kick();
      wheel.dir = dir;
      wheel.size = size;
      clearTimeout(wheel.timer);
      wheel.timer = setTimeout(() => {
        springTo(Math.round(S.target + 0.35 * wheel.dir));
        wheel.lock = { dir: wheel.dir, size: wheel.size, time: performance.now() };
      }, 140);
    },
    { passive: false },
  );

  document.addEventListener("keydown", (e) => {
    if (D.open) {
      if (e.key === "Escape") {
        e.preventDefault();
        closeDetail();
      }
      return;
    }
    if (D.busy || e.altKey || e.metaKey || e.ctrlKey) return;
    if (e.key === "ArrowRight") {
      e.preventDefault();
      step(1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      step(-1);
    } else if (e.key === "Home" && !LOOP) {
      springTo(0);
    } else if (e.key === "End" && !LOOP) {
      springTo(N - 1);
    }
  });

  $("[data-prev]").addEventListener("click", () => step(-1));
  $("[data-next]").addEventListener("click", () => step(1));
  $("[data-open]").addEventListener("click", () => openDetail());

  /* ---------- Detail view ---------- */

  const D = {
    root: $("[data-detail]"),
    stage: $("[data-stage]"),
    camera: $("[data-camera]"),
    name: $("[data-detail-name]"),
    counter: $("[data-detail-counter]"),
    hq: $("[data-detail-hq]"),
    marks: $("[data-marks]"),
    panel: $("[data-facet-panel]"),
    label: $("[data-facet-label]"),
    value: $("[data-facet-value]"),
    text: $("[data-facet-text]"),
    note: $("[data-detail-note]"),
    close: $("[data-close]"),
    tabs: Array.from(document.querySelectorAll("[data-facet]")),
    open: false,
    busy: false,
    facet: "rate",
    cam: null,
    litTimer: 0,
  };

  // Stagger the detail UI's entrance.
  [...D.root.querySelectorAll(".detail-copy > *"), ...D.tabs].forEach((el, i) => el.style.setProperty("--i", i));

  // The part of the stage where the truck is framed: between the text column and the facets on wide screens.
  function framing() {
    const r = D.stage.getBoundingClientRect();
    if (layout.mobile) return { r, x: 0, y: 0, w: r.width, h: r.height };
    const left = r.width * 0.22;
    const right = r.width * 0.15;
    return { r, x: left, y: 0, w: r.width - left - right, h: r.height };
  }

  // Centre the facet's box in the framing, but never pull a photo edge into the stage when the photo can cover it.
  // Each facet's box is its marking on the truck plus a margin (computed on the server, see showroom.py).
  function cameraFor(key) {
    const f = framing();
    const { box, zoom } = data.cameras[key];
    const [bx, by, bw, bh] = box;
    const s = clamp(Math.min(f.w / bw, f.h / bh), 0.1, zoom);
    const keepCovered = (offset, stage, image) => (image >= stage ? clamp(offset, stage - image, 0) : offset);
    const x = keepCovered(f.x + f.w / 2 - (bx + bw / 2) * s, f.r.width, data.scene.width * s);
    const y = keepCovered(f.y + f.h / 2 - (by + bh / 2) * s, f.r.height, data.scene.height * s);
    return { s, x, y, r: f.r };
  }

  function aim(cam, animate) {
    D.camera.classList.toggle("is-moving", animate && !reduced.matches);
    D.camera.style.transform = `translate(${cam.x.toFixed(2)}px, ${cam.y.toFixed(2)}px) scale(${cam.s.toFixed(4)})`;
    D.cam = cam;
  }

  // Where the scene's truck is on screen for a camera: same pixels as the cut-out, so the two line up exactly.
  function sceneTruck(cam) {
    return { x: cam.r.left + cam.x + ORIGIN_X * cam.s, y: cam.r.top + cam.y + ORIGIN_Y * cam.s, s: cam.s };
  }

  function makeFlyer(i, at) {
    const flyer = document.createElement("div");
    flyer.className = "flyer";
    flyer.setAttribute("aria-hidden", "true");
    flyer.style.setProperty("--accent", carriers[i].accent);
    const art = parts[i].art.cloneNode(true);
    art.querySelector(".truck-shade")?.remove();
    flyer.append(art);
    place(flyer, at);
    body.append(flyer);
    return flyer;
  }

  const place = (el, at) => (el.style.transform = `translate(${at.x}px, ${at.y}px) scale(${at.s})`);

  function fly(el, from, to, duration) {
    if (reduced.matches) {
      place(el, to);
      return Promise.resolve();
    }
    const frame = (at) => ({ transform: `translate(${at.x}px, ${at.y}px) scale(${at.s})` });
    const animation = el.animate([frame(from), frame(to)], { duration, easing: "cubic-bezier(0.7, 0, 0.2, 1)" });
    place(el, to);
    return animation.finished.catch(() => {});
  }

  function fillDetail(i) {
    const c = carriers[i];
    D.name.textContent = c.name;
    D.counter.textContent = `${pad(i + 1)} / ${pad(N)}`;
    D.hq.textContent = `${c.hq} merkezli`;
    // The photo gets the same markings as the card (already fitted), on the scene's planes.
    const livery = $(".livery", parts[i].art).cloneNode(true);
    const door = $(".door", parts[i].art).cloneNode(true);
    livery.classList.add("livery-scene");
    door.classList.add("door-scene");
    D.marks.replaceChildren(livery, door);
    for (const tab of D.tabs) {
      const facet = c.facets.find((f) => f.key === tab.dataset.facet);
      $(".facet-mini", tab).textContent = facet ? facet.value : "";
    }
    D.note.hidden = !c.note;
    D.note.textContent = c.note ? `Firma notu: ${c.note}` : "";
  }

  function setFacet(key, move) {
    D.facet = key;
    for (const tab of D.tabs) {
      const on = tab.dataset.facet === key;
      tab.setAttribute("aria-selected", String(on));
      tab.tabIndex = on ? 0 : -1;
    }
    const facet = carriers[S.active].facets.find((f) => f.key === key);
    D.label.textContent = facet.label;
    D.value.textContent = facet.value;
    D.text.textContent = facet.text;
    D.panel.setAttribute("aria-labelledby", `facet-${key}`);
    if (!reduced.matches) {
      D.panel.classList.remove("is-swapping");
      void D.panel.offsetWidth;
      D.panel.classList.add("is-swapping");
    }
    if (move) aim(cameraFor(key), true);
    light(move ? key : null);
  }

  // Light the marking the facet talks about as the camera arrives on it.
  function light(key) {
    clearTimeout(D.litTimer);
    if (key) D.marks.dataset.focus = key;
    else delete D.marks.dataset.focus;
    D.marks.querySelectorAll(".is-lit").forEach((el) => el.classList.remove("is-lit"));
    if (!key || reduced.matches) return;
    D.litTimer = setTimeout(() => $(`[data-decal="${key}"]`, D.marks)?.classList.add("is-lit"), 700);
  }

  async function openDetail() {
    if (D.open || D.busy) return;
    D.busy = true;
    settleNow();
    const i = S.active;
    fillDetail(i);
    setFacet("rate", false);
    D.root.hidden = false;
    D.root.classList.remove("is-open", "is-scene");
    const cam = cameraFor("overview");
    aim(cam, false);

    const flyer = makeFlyer(i, heroRect());
    parts[i].el.style.visibility = "hidden";
    body.classList.add("in-detail");
    hero.classList.add("is-detail");
    hero.inert = true;
    topbar.inert = true; // the dialog keeps the focus
    await fly(flyer, heroRect(), sceneTruck(cam), 1000);

    D.root.classList.add("is-scene"); // the photo's sky and road appear around the truck
    await wait(reduced.matches ? 0 : 520);
    flyer.animate([{ opacity: 1 }, { opacity: 0 }], { duration: reduced.matches ? 0 : 260, fill: "forwards" });
    await wait(reduced.matches ? 0 : 260);
    flyer.remove();

    D.root.classList.add("is-open");
    D.open = true;
    D.busy = false;
    setFacet("rate", true);
    D.tabs[0].focus({ preventScroll: true });
  }

  async function closeDetail() {
    if (!D.open || D.busy) return;
    D.busy = true;
    D.open = false;
    D.root.classList.remove("is-open");
    light(null); // every marking back at full strength for the flight home
    const cam = cameraFor("overview");
    aim(cam, true);
    await wait(reduced.matches ? 0 : 950);

    const i = S.active;
    const flyer = makeFlyer(i, sceneTruck(cam));
    D.root.classList.remove("is-scene");
    body.classList.remove("in-detail");
    hero.classList.remove("is-detail");
    hero.inert = false;
    topbar.inert = false;
    render();
    await fly(flyer, sceneTruck(cam), heroRect(), 950);

    parts[i].el.style.visibility = "";
    flyer.remove();
    D.root.hidden = true;
    D.busy = false;
    parts[i].hit.focus({ preventScroll: true });
  }

  D.close.addEventListener("click", () => closeDetail());
  for (const tab of D.tabs) {
    tab.addEventListener("click", () => {
      if (D.open && tab.dataset.facet !== D.facet) setFacet(tab.dataset.facet, true);
    });
  }
  $("[data-facets]").addEventListener("keydown", (e) => {
    const move = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
    if (!move || !D.open) return;
    e.preventDefault();
    const at = D.tabs.findIndex((t) => t.dataset.facet === D.facet);
    const next = D.tabs[mod(at + move, D.tabs.length)];
    setFacet(next.dataset.facet, true);
    next.focus();
  });

  /* ---------- Colour worlds: radial noise wave (WebGL), CSS glow when WebGL is missing ---------- */

  const noise = createNoise($("[data-noise]"));

  function createNoise(canvas) {
    const none = { to() {}, resize() {} };
    const gl = canvas.getContext("webgl", { antialias: false, alpha: false, powerPreference: "low-power" });
    if (!gl) return none;

    // Ported from the Codrops demo "Model Texture Transition and Procedural Radial Noise using WebGL" (MIT, see its
    // README): the aspect-corrected radial distance, density-scaled noise facets and dots, grain, and two smoothstep
    // circles driven by progress. Classic Perlin noise by Stefan Gustavson (webgl-noise, MIT); the demo samples the
    // 4D version with a constant fourth coordinate, which is this 3D one. Added here: a from/to colour pair, so the
    // stage blends from the previous carrier instead of going dark, and a soft glow that stays after the wave.
    const fragment = `
      #ifdef GL_FRAGMENT_PRECISION_HIGH
      precision highp float;
      #else
      precision mediump float;
      #endif
      uniform vec2 u_res;
      uniform float u_time;
      uniform float u_progress;
      uniform vec3 u_from;
      uniform vec3 u_to;
      uniform vec2 u_center;

      vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
      vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
      vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
      vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
      vec3 fade(vec3 t) { return t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }

      float cnoise(vec3 P) {
        vec3 Pi0 = mod289(floor(P));
        vec3 Pi1 = mod289(Pi0 + vec3(1.0));
        vec3 Pf0 = fract(P);
        vec3 Pf1 = Pf0 - vec3(1.0);
        vec4 ix = vec4(Pi0.x, Pi1.x, Pi0.x, Pi1.x);
        vec4 iy = vec4(Pi0.yy, Pi1.yy);
        vec4 ixy = permute(permute(ix) + iy);
        vec4 ixy0 = permute(ixy + Pi0.zzzz);
        vec4 ixy1 = permute(ixy + Pi1.zzzz);
        vec4 gx0 = ixy0 * (1.0 / 7.0);
        vec4 gy0 = fract(floor(gx0) * (1.0 / 7.0)) - 0.5;
        gx0 = fract(gx0);
        vec4 gz0 = vec4(0.5) - abs(gx0) - abs(gy0);
        vec4 sz0 = step(gz0, vec4(0.0));
        gx0 -= sz0 * (step(0.0, gx0) - 0.5);
        gy0 -= sz0 * (step(0.0, gy0) - 0.5);
        vec4 gx1 = ixy1 * (1.0 / 7.0);
        vec4 gy1 = fract(floor(gx1) * (1.0 / 7.0)) - 0.5;
        gx1 = fract(gx1);
        vec4 gz1 = vec4(0.5) - abs(gx1) - abs(gy1);
        vec4 sz1 = step(gz1, vec4(0.0));
        gx1 -= sz1 * (step(0.0, gx1) - 0.5);
        gy1 -= sz1 * (step(0.0, gy1) - 0.5);
        vec3 g000 = vec3(gx0.x, gy0.x, gz0.x);
        vec3 g100 = vec3(gx0.y, gy0.y, gz0.y);
        vec3 g010 = vec3(gx0.z, gy0.z, gz0.z);
        vec3 g110 = vec3(gx0.w, gy0.w, gz0.w);
        vec3 g001 = vec3(gx1.x, gy1.x, gz1.x);
        vec3 g101 = vec3(gx1.y, gy1.y, gz1.y);
        vec3 g011 = vec3(gx1.z, gy1.z, gz1.z);
        vec3 g111 = vec3(gx1.w, gy1.w, gz1.w);
        vec4 norm0 = taylorInvSqrt(vec4(dot(g000, g000), dot(g010, g010), dot(g100, g100), dot(g110, g110)));
        g000 *= norm0.x; g010 *= norm0.y; g100 *= norm0.z; g110 *= norm0.w;
        vec4 norm1 = taylorInvSqrt(vec4(dot(g001, g001), dot(g011, g011), dot(g101, g101), dot(g111, g111)));
        g001 *= norm1.x; g011 *= norm1.y; g101 *= norm1.z; g111 *= norm1.w;
        float n000 = dot(g000, Pf0);
        float n100 = dot(g100, vec3(Pf1.x, Pf0.yz));
        float n010 = dot(g010, vec3(Pf0.x, Pf1.y, Pf0.z));
        float n110 = dot(g110, vec3(Pf1.xy, Pf0.z));
        float n001 = dot(g001, vec3(Pf0.xy, Pf1.z));
        float n101 = dot(g101, vec3(Pf1.x, Pf0.y, Pf1.z));
        float n011 = dot(g011, vec3(Pf0.x, Pf1.yz));
        float n111 = dot(g111, Pf1);
        vec3 f = fade(Pf0);
        vec4 nz = mix(vec4(n000, n100, n010, n110), vec4(n001, n101, n011, n111), f.z);
        vec2 nyz = mix(nz.xy, nz.zw, f.y);
        return 2.2 * mix(nyz.x, nyz.y, f.x);
      }

      void main() {
        vec2 uv = gl_FragCoord.xy / u_res;
        vec2 p = (uv - u_center) * vec2(u_res.x / u_res.y, 1.0);
        float dist = length(p);
        float density = 1.8 - dist;
        float n = cnoise(vec3(p * 40.0 * density, u_time));
        float grain = fract(sin(dot(uv, vec2(12.9898, 78.233) * 2000.0)) * 43758.5453);
        float facets = n * 2.0;
        float dots = smoothstep(0.1, 0.15, n);
        float pattern = step(0.2, facets) * dots;

        float radius = 1.9;
        float outer = clamp(1.1 * u_progress, 0.0, 1.0);
        float inner = clamp(1.1 * u_progress - 0.05, 0.0, 1.0);
        float innerCircle = 1.0 - smoothstep((inner - 0.4) * radius, inner * radius, dist);
        float outerCircle = 1.0 - smoothstep((outer - 0.1) * radius, inner * radius, dist);
        float ring = clamp(outerCircle - innerCircle, 0.0, 1.0);

        float glow = exp(-dist * 2.3) * 0.5 + exp(-dist * 6.5) * 0.22;
        vec3 world = mix(u_from, u_to, innerCircle) * glow;
        float edge = ring * (0.35 + pattern * 0.9 + n * 0.5);
        vec3 color = world + u_to * max(edge, 0.0) * 0.65 - vec3(grain * 0.03);
        gl_FragColor = vec4(max(color, 0.0), 1.0);
      }`;
    const vertex = "attribute vec2 a; void main() { gl_Position = vec4(a, 0.0, 1.0); }";

    const shader = (type, source) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, source);
      gl.compileShader(s);
      return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null;
    };
    const vs = shader(gl.VERTEX_SHADER, vertex);
    const fs = shader(gl.FRAGMENT_SHADER, fragment);
    if (!vs || !fs) return none;
    const program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return none;
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW); // one big triangle
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    const u = Object.fromEntries(
      ["u_res", "u_time", "u_progress", "u_from", "u_to", "u_center"].map((n) => [n, gl.getUniformLocation(program, n)]),
    );
    body.classList.add("has-gl");

    const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
    const state = { from: [0, 0, 0], to: [0, 0, 0], start: 0, progress: 1, raf: 0, timer: 0, born: performance.now() };

    function draw(now) {
      gl.uniform2f(u.u_res, canvas.width, canvas.height);
      gl.uniform1f(u.u_time, (now - state.born) / 1000);
      gl.uniform1f(u.u_progress, state.progress);
      gl.uniform3fv(u.u_from, state.from);
      gl.uniform3fv(u.u_to, state.to);
      gl.uniform2f(u.u_center, 0.5, 1 - (layout.floor - layout.W * 0.2) / window.innerHeight); // behind the hero truck
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }

    function frame(now) {
      const t = clamp((now - state.start) / 2000, 0, 1);
      state.progress = 1 - (1 - t) * (1 - t); // easeQuadOut, as in the demo
      draw(now);
      state.raf = t < 1 && !document.hidden ? requestAnimationFrame(frame) : 0; // idle: no frames at all
    }

    function begin(hex) {
      const e = state.progress;
      state.from = state.from.map((v, i) => v + (state.to[i] - v) * e); // continue from what is on screen
      state.to = rgb(hex);
      state.start = performance.now();
      if (reduced.matches) {
        state.progress = 1;
        draw(state.start);
        return;
      }
      state.progress = 0;
      if (!state.raf) state.raf = requestAnimationFrame(frame);
    }

    function resize() {
      const scale = Math.min(window.devicePixelRatio || 1, 1) * (window.innerWidth < 760 ? 0.5 : 0.75);
      canvas.width = Math.max(1, Math.round(window.innerWidth * scale));
      canvas.height = Math.max(1, Math.round(window.innerHeight * scale));
      gl.viewport(0, 0, canvas.width, canvas.height);
      draw(performance.now()); // resizing clears the canvas even when idle
    }

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && state.progress < 1 && !state.raf) state.raf = requestAnimationFrame(frame);
    });

    resize();
    return {
      to(hex) {
        clearTimeout(state.timer);
        state.timer = setTimeout(() => begin(hex), 90); // a fast drag passes many trucks: colour the one it stops on
      },
      resize,
    };
  }

  /* ---------- Start ---------- */

  // The server already picked the carrier from the path (/a-logistics). Links from before addresses had a path
  // (#a-logistics, #firma-<id>) still open the same carrier.
  const fromHash = (() => {
    try {
      return decodeURIComponent(location.hash.slice(1)).toLowerCase();
    } catch {
      return "";
    }
  })();
  const oldId = /^firma-(\d+)$/.exec(fromHash)?.[1];
  const hashIndex = fromHash ? carriers.findIndex((c) => c.slug === fromHash || String(c.id) === oldId) : -1;
  const startIndex = hashIndex >= 0 ? hashIndex : data.start || 0;
  measure();
  S.pos = S.target = startIndex;
  render();
  settled();

  let resizeTimer = 0;
  window.addEventListener("resize", () => {
    measure();
    render();
    noise.resize();
    clearTimeout(resizeTimer);
    if (D.open) resizeTimer = setTimeout(() => aim(cameraFor(D.facet), false), 60);
  });
})();
