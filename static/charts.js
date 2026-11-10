// Inline-SVG charts, no library: smooth line chart (draws itself in, crosshair, focusable
// legend, labels at the line ends), stacked bars that grow in, an organic funnel, sparklines
// and the competitor orbit. Labels go in with textContent, never as HTML.

const NS = "http://www.w3.org/2000/svg";
export const SERIES = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5", "--series-6"];
let uid = 0;

function el(name, attrs = {}, parent) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (parent) parent.appendChild(node);
  return node;
}

function niceMax(value) {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (step * magnitude >= value) return step * magnitude;
  return 10 * magnitude;
}

const tooltip = () => document.getElementById("tooltip");

export function showTooltip(event, title, rows) {
  const tip = tooltip();
  tip.replaceChildren();
  const head = document.createElement("div");
  head.className = "meta";
  head.textContent = title;
  tip.appendChild(head);
  for (const row of rows) {
    const line = document.createElement("div");
    line.className = "row";
    const key = document.createElement("span");
    key.className = "key";
    key.style.setProperty("--key", `var(${row.color})`);
    const value = document.createElement("strong");
    value.textContent = row.value;
    const name = document.createElement("span");
    name.textContent = row.name;
    line.append(key, value, name);
    tip.appendChild(line);
  }
  tip.hidden = false;
  const x = Math.min(event.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
  tip.style.left = `${x}px`;
  tip.style.top = `${event.clientY + 14}px`;
}

export const hideTooltip = () => (tooltip().hidden = true);

function title(container, text) {
  if (!text) return;
  const node = document.createElement("div");
  node.className = "meta";
  node.textContent = text;
  container.appendChild(node);
}

// Legend entries are buttons: hovering one brings its series forward, clicking hides it.
function legend(container, series, svg, bars = false) {
  if (series.length < 2) return;
  const box = document.createElement("div");
  box.className = bars ? "legend bars" : "legend";
  for (const s of series) {
    const item = document.createElement("button");
    item.type = "button";
    item.style.setProperty("--key", `var(${s.color})`);
    item.textContent = s.name;
    if (!bars) {
      const focus = (on) => svg.querySelectorAll("[data-series]").forEach((g) => g.classList.toggle("dim", on && g.dataset.series !== s.name));
      item.addEventListener("pointerenter", () => focus(true));
      item.addEventListener("pointerleave", () => focus(false));
      item.addEventListener("click", () => {
        const off = item.classList.toggle("off");
        svg.querySelectorAll(`[data-series="${CSS.escape(s.name)}"]`).forEach((g) => g.classList.toggle("off", off));
      });
    }
    box.appendChild(item);
  }
  container.appendChild(box);
}

// Monotone cubic through the points: smooth, but never overshoots the data.
function smoothPath(points) {
  if (points.length < 3) return points.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join("");
  const n = points.length;
  const dx = [], m = [], t = [];
  for (let i = 0; i < n - 1; i++) {
    dx[i] = points[i + 1].x - points[i].x;
    m[i] = (points[i + 1].y - points[i].y) / dx[i];
  }
  t[0] = m[0];
  t[n - 1] = m[n - 2];
  for (let i = 1; i < n - 1; i++)
    t[i] = m[i - 1] * m[i] <= 0 ? 0 : (3 * (dx[i - 1] + dx[i])) / ((2 * dx[i] + dx[i - 1]) / m[i - 1] + (dx[i] + 2 * dx[i - 1]) / m[i]);
  let d = `M${points[0].x},${points[0].y}`;
  for (let i = 0; i < n - 1; i++) {
    const a = points[i], b = points[i + 1], k = dx[i] / 3;
    d += `C${a.x + k},${a.y + t[i] * k} ${b.x - k},${b.y - t[i + 1] * k} ${b.x},${b.y}`;
  }
  return d;
}

function runs(values, x, y) {
  const out = [];
  let current = [];
  values.forEach((v, i) => {
    if (v == null) {
      if (current.length) out.push(current);
      current = [];
    } else current.push({ x: x(i), y: y(v) });
  });
  if (current.length) out.push(current);
  return out;
}

// series: [{name, color, values: [number|null per x]}]; xLabels: strings; format: number -> text
export function lineChart(container, { xLabels, series, format, title: heading }) {
  container.replaceChildren();
  container.classList.add("chart");
  title(container, heading);
  const ends = series.length > 1;
  const width = Math.max(320, container.clientWidth - 32), height = 250, left = 50, right = ends ? 104 : 20, top = 14, bottom = 28;
  const plotW = width - left - right, plotH = height - top - bottom;
  const all = series.flatMap((s) => s.values).filter((v) => v != null);
  const max = niceMax(Math.max(0, ...all));
  const x = (i) => left + (xLabels.length < 2 ? plotW / 2 : (i * plotW) / (xLabels.length - 1));
  const y = (v) => top + plotH - (v / max) * plotH;
  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": heading || "Line chart" });
  legend(container, series, svg);

  for (let t = 0; t <= 4; t++) {
    const value = (max * t) / 4;
    el("line", { x1: left, x2: width - right, y1: y(value), y2: y(value), class: t ? "grid-line" : "axis-line" }, svg);
    el("text", { x: left - 8, y: y(value) + 4, "text-anchor": "end" }, svg).textContent = format(value, true);
  }
  const every = Math.ceil(xLabels.length / 8);
  xLabels.forEach((label, i) => {
    if (i % every === 0 || i === xLabels.length - 1) el("text", { x: x(i), y: height - 8, "text-anchor": "middle" }, svg).textContent = label;
  });

  const labels = [];
  series.forEach((s, index) => {
    const g = el("g", { "data-series": s.name, class: "series", style: `--c: var(${s.color}); --d: ${index * 120}ms` }, svg);
    const segments = runs(s.values, x, y);
    if (!ends) {
      const gid = `fade-${++uid}`;
      const grad = el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, el("defs", {}, svg));
      el("stop", { offset: "0%", "stop-color": `var(${s.color})`, "stop-opacity": 0.22 }, grad);
      el("stop", { offset: "100%", "stop-color": `var(${s.color})`, "stop-opacity": 0 }, grad);
      for (const pts of segments)
        el("path", { d: `${smoothPath(pts)}L${pts.at(-1).x},${top + plotH}L${pts[0].x},${top + plotH}Z`, fill: `url(#${gid})`, class: "area" }, g);
    }
    for (const pts of segments) el("path", { d: smoothPath(pts), class: "line", pathLength: 1 }, g);
    const last = s.values.findLastIndex((v) => v != null);
    if (last >= 0) {
      el("circle", { cx: x(last), cy: y(s.values[last]), r: 3.5, class: "end-dot" }, g);
      if (ends) labels.push({ g, y: y(s.values[last]), x: x(last), text: s.name, value: format(s.values[last]) });
    }
  });
  // End labels, nudged apart so they never sit on top of each other.
  labels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 14);
  for (const l of labels) {
    const t = el("text", { x: l.x + 10, y: l.y + 4, class: "end-label" }, l.g);
    t.textContent = l.text;
  }

  const cross = el("line", { y1: top, y2: top + plotH, class: "cross", visibility: "hidden" }, svg);
  const marks = series.map((s) => el("circle", { r: 4, class: "hover-dot", style: `--c: var(${s.color})`, visibility: "hidden" }, svg));
  const hit = el("rect", { x: left, y: top, width: plotW, height: plotH, fill: "transparent" }, svg);
  hit.addEventListener("pointermove", (event) => {
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * width;
    const i = xLabels.length < 2 ? 0 : Math.max(0, Math.min(xLabels.length - 1, Math.round(((px - left) / plotW) * (xLabels.length - 1))));
    cross.setAttribute("x1", x(i));
    cross.setAttribute("x2", x(i));
    cross.setAttribute("visibility", "visible");
    series.forEach((s, k) => {
      const v = s.values[i];
      const hidden = v == null || svg.querySelector(`[data-series="${CSS.escape(s.name)}"].off`);
      marks[k].setAttribute("visibility", hidden ? "hidden" : "visible");
      if (!hidden) {
        marks[k].setAttribute("cx", x(i));
        marks[k].setAttribute("cy", y(v));
      }
    });
    showTooltip(event, xLabels[i], series.map((s) => ({ name: s.name, color: s.color, value: s.values[i] == null ? "–" : format(s.values[i]) })));
  });
  hit.addEventListener("pointerleave", () => {
    cross.setAttribute("visibility", "hidden");
    marks.forEach((m) => m.setAttribute("visibility", "hidden"));
    hideTooltip();
  });
  container.appendChild(svg);
}

// rows: [{label, parts: [number per segment]}]; segments: [{name, color}]
export function stackedBars(container, { rows, segments, title: heading }) {
  container.replaceChildren();
  container.classList.add("chart");
  title(container, heading);
  const width = Math.max(320, container.clientWidth - 32), left = 110, right = 40, rowH = 34, bar = 18;
  const height = rows.length * rowH + 8;
  const max = niceMax(Math.max(1, ...rows.map((r) => r.parts.reduce((a, b) => a + b, 0))));
  const scale = (v) => (v / max) * (width - left - right);
  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": heading || "Bar chart" });
  legend(container, segments, svg, true);
  rows.forEach((row, r) => {
    const yTop = r * rowH + (rowH - bar) / 2 + 4;
    el("text", { x: left - 10, y: yTop + bar / 2 + 4, "text-anchor": "end", class: "bar-label" }, svg).textContent = row.label;
    el("rect", { x: left, y: yTop, width: width - left - right, height: bar, rx: 4, class: "bar-track" }, svg);
    const g = el("g", { class: "grow", style: `--d: ${r * 90}ms` }, svg);
    let offset = left;
    const total = row.parts.reduce((a, b) => a + b, 0);
    row.parts.forEach((value, s) => {
      if (!value) return;
      const w = Math.max(scale(value) - 2, 2);
      const shape = el("rect", { x: offset, y: yTop, width: w, height: bar, rx: 4, fill: `var(${segments[s].color})`, class: "bar-seg" }, g);
      shape.setAttribute("tabindex", "0");
      const share = total ? ` (${Math.round((value / total) * 100)}%)` : "";
      const show = (event) => showTooltip(event, row.label, [{ name: segments[s].name, color: segments[s].color, value: `${value}${share}` }]);
      shape.addEventListener("pointermove", show);
      shape.addEventListener("pointerleave", hideTooltip);
      offset += scale(value);
    });
    el("text", { x: left + scale(total) + 8, y: yTop + bar / 2 + 4, class: "bar-total" }, svg).textContent = String(total);
  });
  container.appendChild(svg);
}

// An organic funnel flowing left to right. stages: [{name, value, before}], format: n -> text.
// Band height follows the square root of the value, so the narrow end stays readable.
export function funnelShape(container, { stages, format, compare }) {
  container.replaceChildren();
  container.classList.add("chart", "funnel");
  const width = Math.max(320, container.clientWidth - 32), height = 230, mid = 128, maxH = 150, minH = 14;
  const top = Math.max(1, ...stages.map((s) => s.value));
  const span = (v) => minH + Math.sqrt(Math.max(0, v) / top) * (maxH - minH);
  const step = width / stages.length;
  const cx = (i) => step * i + step / 2;
  const gid = `funnel-${++uid}`;
  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": stages.map((s) => `${s.name} ${format(s.value)}`).join(", ") });
  const grad = el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 1, y2: 0 }, el("defs", {}, svg));
  el("stop", { offset: "0%", "stop-color": "var(--series-1)", "stop-opacity": 0.9 }, grad);
  el("stop", { offset: "100%", "stop-color": "var(--series-5)", "stop-opacity": 0.55 }, grad);

  // Top edge left to right, then bottom edge back, each a chain of S-curves between stages.
  const pts = stages.map((s, i) => ({ x: cx(i), h: span(s.value) / 2 }));
  const first = { x: 0, h: pts[0].h }, last = { x: width, h: pts.at(-1).h };
  const chain = [first, ...pts, last];
  let d = `M${chain[0].x},${mid - chain[0].h}`;
  for (let i = 1; i < chain.length; i++) {
    const a = chain[i - 1], b = chain[i], k = (b.x - a.x) / 2;
    d += `C${a.x + k},${mid - a.h} ${b.x - k},${mid - b.h} ${b.x},${mid - b.h}`;
  }
  d += `L${chain.at(-1).x},${mid + chain.at(-1).h}`;
  for (let i = chain.length - 1; i > 0; i--) {
    const a = chain[i], b = chain[i - 1], k = (a.x - b.x) / 2;
    d += `C${a.x - k},${mid + a.h} ${b.x + k},${mid + b.h} ${b.x},${mid + b.h}`;
  }
  el("path", { d: `${d}Z`, fill: `url(#${gid})`, class: "funnel-body" }, svg);

  stages.forEach((s, i) => {
    if (i) el("line", { x1: step * i, x2: step * i, y1: 14, y2: height - 10, class: "funnel-divider" }, svg);
    el("text", { x: cx(i), y: 30, "text-anchor": "middle", class: "funnel-name" }, svg).textContent = s.name;
    el("text", { x: cx(i), y: mid + 9, "text-anchor": "middle", class: "funnel-value" }, svg).textContent = format(s.value);
    if (s.before != null && s.before !== 0) {
      const change = (s.value - s.before) / s.before;
      const up = change > 0;
      el("text", { x: cx(i), y: height - 18, "text-anchor": "middle", class: `funnel-delta ${change === 0 ? "" : up ? "up" : "down"}` }, svg).textContent =
        `${change > 0 ? "▲" : change < 0 ? "▼" : ""} ${Math.abs(Math.round(change * 100))}% ${compare}`;
    }
    if (i) {
      const rate = stages[i - 1].value ? s.value / stages[i - 1].value : null;
      const g = el("g", { class: "funnel-rate" }, svg);
      el("rect", { x: step * i - 26, y: mid - 11, width: 52, height: 22, rx: 11 }, g);
      el("text", { x: step * i, y: mid + 4, "text-anchor": "middle" }, g).textContent = rate == null ? "–" : `${(rate * 100).toFixed(rate < 0.1 ? 1 : 0)}%`;
    }
  });
  container.appendChild(svg);
}

// A tiny trend line for table cells.
export function sparkline(values, color = "--series-1") {
  const width = 84, height = 24, pad = 3;
  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, class: "spark", "aria-hidden": "true" });
  const nums = values.filter((v) => v != null);
  if (nums.length < 2) return svg;
  const max = Math.max(...nums), min = Math.min(0, ...nums);
  const x = (i) => pad + (i * (width - pad * 2)) / (values.length - 1);
  const y = (v) => height - pad - ((v - min) / (max - min || 1)) * (height - pad * 2);
  for (const pts of runs(values, x, y)) el("path", { d: smoothPath(pts), style: `--c: var(${color})`, pathLength: 1 }, svg);
  const last = values.findLastIndex((v) => v != null);
  el("circle", { cx: x(last), cy: y(values[last]), r: 2.2, style: `--c: var(${color})` }, svg);
  return svg;
}

// A hand-drawn-looking ring: a circle whose radius wobbles a little, so the map feels sketched.
function wobble(cx, cy, r, seed) {
  let d = "";
  for (let i = 0; i <= 96; i++) {
    const a = (i / 96) * Math.PI * 2;
    const rr = r * (1 + 0.018 * Math.sin(3 * a + seed) + 0.012 * Math.sin(5 * a + seed * 2.3));
    d += `${i ? "L" : "M"}${(cx + rr * Math.cos(a)).toFixed(1)},${(cy + rr * Math.sin(a)).toFixed(1)}`;
  }
  return `${d}Z`;
}

// items: [{name, color (css value), closeness 0..1 or null, size, detail, fresh, href}]
export function orbit(container, { center, items }) {
  container.replaceChildren();
  const W = 460, H = 420, cx = W / 2, cy = H / 2;
  const inner = 70, outer = 165, unknown = 192;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Competitors around ${center}: closer means we lose more deals to them` });

  el("path", { d: wobble(cx, cy, inner + 8, 1.3), class: "orbit-zone" }, svg);
  [[inner + 8, 1.3], [(inner + outer) / 2, 2.1], [outer, 0.4]].forEach(([r, s]) => el("path", { d: wobble(cx, cy, r, s), class: "orbit-ring" }, svg));
  el("path", { d: wobble(cx, cy, unknown, 3.2), class: "orbit-ring dashed" }, svg);
  el("text", { x: cx, y: cy - inner - 14, class: "orbit-note", "text-anchor": "middle" }, svg).textContent = "they win";
  el("text", { x: cx, y: cy - outer + 14, class: "orbit-note", "text-anchor": "middle" }, svg).textContent = "we win";
  el("text", { x: cx, y: cy + unknown + 16, class: "orbit-note", "text-anchor": "middle" }, svg).textContent = "not met in deals yet";

  el("circle", { cx, cy, r: 34, class: "orbit-core" }, svg);
  el("text", { x: cx, y: cy + 5, class: "orbit-core-label", "text-anchor": "middle" }, svg).textContent = center;

  items.forEach((item, i) => {
    const angle = -Math.PI / 2 + 0.55 + (i * Math.PI * 2) / items.length;
    const r = item.closeness == null ? unknown : inner + 14 + item.closeness * (outer - inner - 14);
    const x = cx + r * Math.cos(angle), y = cy + r * Math.sin(angle);
    const dot = 5 + Math.sqrt(item.size || 0) * 2.6;
    const link = el("a", { href: item.href, class: "orbit-item" }, svg);
    link.style.setProperty("--c", item.color);
    el("line", { x1: cx, y1: cy, x2: x, y2: y, class: "orbit-tether" }, link);
    if (item.fresh) el("circle", { cx: x, cy: y, r: dot + 4, class: "orbit-pulse" }, link);
    el("circle", { cx: x, cy: y, r: dot, class: "orbit-dot" }, link);
    const right = x >= cx;
    const tx = x + (right ? dot + 8 : -dot - 8);
    el("text", { x: tx, y: y - 1, "text-anchor": right ? "start" : "end", class: "orbit-name" }, link).textContent = item.name;
    el("text", { x: tx, y: y + 13, "text-anchor": right ? "start" : "end", class: "orbit-detail" }, link).textContent = item.detail;
    link.addEventListener("pointermove", (event) =>
      showTooltip(event, item.name, [{ name: item.fresh ? `${item.detail} · ${item.fresh} new this week` : item.detail, color: "--accent", value: "" }]),
    );
    link.addEventListener("pointerleave", hideTooltip);
  });
  container.appendChild(svg);
}
