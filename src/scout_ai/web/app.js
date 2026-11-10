// Scout AI dashboard (guide Step 10), in the Confience brand.
// The story it tells: what competitors are doing → where it costs us → what we can do next.
// Every text from the API goes in through textContent; only the summaries' Markdown is
// rendered to HTML, by a renderer that escapes everything first.

import { funnelShape, lineChart, orbit, SERIES, sparkline, stackedBars } from "./charts.js";
import { DIMENSIONS, MYLIMS, PROFILES } from "./competitors.js";
import { renderMarkdown } from "./markdown.js";

const view = document.getElementById("view");
const SEEN_KEY = "scout.lastSeenSummary";
let meta = null;

// --- helpers ---

function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "style") node.style.cssText = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
  return body;
}

const query = (params) => {
  const entries = Object.entries(params).filter(([, v]) => v != null && v !== "");
  return entries.length ? `?${new URLSearchParams(entries)}` : "";
};

const int = new Intl.NumberFormat("en-US");
const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const compactMoney = (v) => `$${compact.format(v)}`;
const monthName = (iso) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
// A date-only value ("2026-11-10") is a calendar day: show it as is, not shifted to local time.
const day = (iso) =>
  new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso).toLocaleDateString("en-US", {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(iso.length === 10 ? { timeZone: "UTC" } : {}),
  });
const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const label = (text) => text.replaceAll("_", " ");
const capital = (text) => text.charAt(0).toUpperCase() + text.slice(1);
const hashFor = (name) => `#/competitors/${encodeURIComponent(name)}`;

function compColor(name) {
  const known = ["labware", "starlims", "clinisys", "labvantage", "cloudlims"];
  const key = name.toLowerCase();
  return known.includes(key) ? `var(--c-${key})` : "var(--accent)";
}

function comp(name, linked = true) {
  const inner = [h("span", { class: "dot", style: `--c:${compColor(name)}` }), name];
  return linked ? h("a", { class: "comp", href: hashFor(name), style: "text-decoration:none" }, inner) : h("span", { class: "comp" }, inner);
}

function delta(now, before, { upIsGood = true } = {}) {
  if (!before) return h("span", { class: "delta" }, "no previous value");
  const change = (now - before) / before;
  const good = change === 0 || upIsGood == null ? null : change > 0 === upIsGood;
  const cls = good == null ? "delta" : good ? "delta up" : "delta down";
  return h("span", { class: cls }, `${change > 0 ? "▲" : change < 0 ? "▼" : ""} ${Math.abs(Math.round(change * 100))}% vs previous month`);
}

function field(name, control) {
  return h("div", { class: "field" }, name, control);
}

function select(name, options, value, onchange) {
  return field(
    name,
    h(
      "select",
      { "aria-label": name, onchange: (e) => onchange(e.target.value) },
      options.map(([v, text]) => h("option", { value: v, selected: v === value }, text)),
    ),
  );
}

function segmented(name, options, value, onchange) {
  return field(
    name,
    h(
      "div",
      { class: "segmented", role: "group", "aria-label": name },
      options.map(([v, text, extra]) =>
        h("button", { type: "button", "aria-pressed": String(v === value), onclick: () => onchange(v) }, extra, text),
      ),
    ),
  );
}

// A sortable table: click a header to sort. Numeric columns can carry an inline bar scaled to
// the column's largest value, a change against an earlier value, or a sparkline.
// columns: [{key, label, num, format(v, row), bar: "--color", delta: key, lowerIsBetter, spark: key, sparkColor, cell(row)}]
function dataTable({ columns, rows, sortKey = null, note }) {
  let sort = { key: sortKey, dir: -1 };
  const maxOf = {};
  for (const c of columns) if (c.bar) maxOf[c.key] = Math.max(0, ...rows.map((r) => Math.abs(r[c.key] ?? 0)));
  const headRow = h("tr");
  const tbody = h("tbody");

  const cellFor = (c, row) => {
    if (c.cell) return h("td", { class: c.num ? "num" : null }, c.cell(row));
    if (c.spark) return h("td", { class: "spark-cell" }, sparkline(row[c.spark], c.sparkColor));
    const v = row[c.key];
    if (!c.num) return h("td", {}, v == null ? "–" : c.format ? c.format(v, row) : v);
    const parts = [h("span", { class: "cell-v" }, v == null ? "–" : c.format ? c.format(v, row) : String(v))];
    const before = c.delta ? row[c.delta] : null;
    if (v != null && before) {
      const change = (v - before) / before;
      const good = change === 0 || c.neutral ? null : change > 0 !== Boolean(c.lowerIsBetter);
      parts.push(
        h("span", { class: `cell-d ${good == null ? "" : good ? "up" : "down"}`, title: `before: ${c.format ? c.format(before, row) : before}` }, `${change > 0 ? "▲" : change < 0 ? "▼" : "="}${change ? Math.abs(Math.round(change * 100)) + "%" : ""}`),
      );
    }
    const td = h("td", { class: "num" }, parts);
    if (c.bar && v != null && maxOf[c.key]) {
      td.classList.add("has-bar");
      td.style.setProperty("--wn", (Math.abs(v) / maxOf[c.key]).toFixed(3));
      td.style.setProperty("--b", `var(${c.bar})`);
    }
    return td;
  };

  const draw = () => {
    const sorted = sort.key == null
      ? rows
      : [...rows].sort((a, b) => {
          const va = a[sort.key], vb = b[sort.key];
          if (va == null) return 1;
          if (vb == null) return -1;
          return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * sort.dir;
        });
    tbody.replaceChildren(...sorted.map((row, i) => h("tr", { style: `--i:${Math.min(i, 14)}` }, columns.map((c) => cellFor(c, row)))));
    headRow.querySelectorAll("th[data-key]").forEach((th) => th.setAttribute("aria-sort", th.dataset.key === sort.key ? (sort.dir > 0 ? "ascending" : "descending") : "none"));
  };

  for (const c of columns) {
    const sortable = !c.spark && c.sortable !== false;
    headRow.append(
      h(
        "th",
        { class: c.num ? "num" : c.spark ? "spark-cell" : null, "data-key": sortable ? c.sortBy || c.key : null },
        sortable
          ? h("button", { type: "button", class: "sort", onclick: () => {
              const key = c.sortBy || c.key;
              sort = { key, dir: sort.key === key ? -sort.dir : c.num ? -1 : 1 };
              draw();
            } }, c.label)
          : c.label,
      ),
    );
  }
  draw();
  return h("div", {}, h("div", { class: "table-wrap" }, h("table", { class: "data" }, h("thead", {}, headRow), tbody)), note && h("p", { class: "note" }, note));
}

function link(url, text) {
  return /^https?:\/\//i.test(url || "")
    ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, text)
    : text;
}

function head(_group, title, lead) {
  return h("div", { class: "page-head" }, h("h1", {}, title), lead && h("p", { class: "lead" }, lead));
}

function section(title, sub, more, ...content) {
  return h(
    "section",
    { class: "section" },
    h("div", { class: "section-head" }, h("div", {}, h("h2", {}, title), sub && h("p", {}, sub)), more),
    ...content,
  );
}

function crumbs(...parts) {
  document.getElementById("crumb").replaceChildren(
    ...parts.map(([text, href]) => h("span", {}, href ? h("a", { href }, text) : text)),
  );
}

function render(...nodes) {
  view.replaceChildren(...nodes.flat().filter(Boolean));
}

const empty = (text) => h("div", { class: "empty-card" }, text);

// Which competitors a recommendation is about: named in its action or its evidence.
function competitorsIn(rec, names) {
  const text = [rec.action, ...rec.evidence.flatMap((e) => [e.label, e.fact, e.note])].join(" ").toLowerCase();
  return names.filter((n) => text.includes(n.toLowerCase()));
}

// --- briefings badge ---

async function refreshBadge(list) {
  list = list || (await api("/notifications"));
  let seen = null;
  try {
    seen = localStorage.getItem(SEEN_KEY);
  } catch {}
  document.getElementById("badge").hidden = !list.length || String(list[0].id) === seen;
  return list;
}

function markSeen(id) {
  try {
    localStorage.setItem(SEEN_KEY, String(id));
  } catch {}
  document.getElementById("badge").hidden = true;
}

function setPlaysCount(recs) {
  const n = recs.filter((r) => r.status === "proposed").length;
  const node = document.getElementById("plays-count");
  node.textContent = String(n);
  node.hidden = !n;
}

// --- overview ---

async function overview() {
  crumbs(["Overview"]);
  const [competitors, signalsList, deals, recs, briefs] = await Promise.all([
    api("/competitors"),
    api("/signals?limit=5"),
    api("/deals/competition"),
    api("/recommendations"),
    api("/notifications"),
  ]);
  refreshBadge(briefs);
  setPlaysCount(recs);
  const names = competitors.map((c) => c.name);
  const won = deals.competitors.reduce((a, c) => a + c.won, 0);
  const lost = deals.competitors.reduce((a, c) => a + c.lost, 0);
  const open = deals.competitors.reduce((a, c) => a + c.open, 0);
  const amountLost = deals.competitors.reduce((a, c) => a + c.amount_lost, 0);
  const moves = competitors.reduce((a, c) => a + c.signals_last_7_days, 0);
  const proposed = recs.filter((r) => r.status === "proposed").sort((a, b) => b.priority - a.priority);

  // The page opens with what a colleague would tell you, then the numbers behind it.
  // Key figures get a highlighter stroke, like notes on a printed report.
  const mark = (text) => h("mark", {}, text);
  const story = h(
    "p",
    { class: "story" },
    moves ? [mark(`${moves} new ${moves === 1 ? "move" : "moves"}`), " from competitors this week. "] : "A quiet week: no new competitor moves. ",
    won + lost ? ["We won ", mark(`${won} of ${won + lost}`), ` head-to-head deals in ${deals.year} and lost `, mark(compactMoney(amountLost)), " to them. "] : "",
    proposed.length ? h("a", { href: "#/plays" }, `${proposed.length} ${proposed.length === 1 ? "play is" : "plays are"} waiting for you →`) : "Nothing is waiting for review.",
  );
  const orbitBox = h("div", { class: "orbit" });
  const stat = (value, text) => h("div", { class: "stat" }, h("div", { class: "value" }, value), h("div", { class: "label" }, text));

  const theirMoves = signalsList.length
    ? h(
        "div",
        { class: "rows" },
        signalsList.map((s) =>
          h(
            "a",
            { class: "row", href: `#/signals?competitor=${encodeURIComponent(s.competitor)}&days=all` },
            h("span", { class: "dot", style: `--c:${compColor(s.competitor)}` }),
            h("span", { class: "row-main" }, h("span", { class: "row-title" }, s.title), h("span", { class: "row-sub" }, `${s.competitor} · ${label(s.type)}`)),
            h("span", { class: "row-end" }, day(s.detected_at)),
          ),
        ),
      )
    : empty("No moves detected yet. Run scout collect and scout analyze.");

  const ourPlays = proposed.length
    ? h(
        "div",
        { class: "rows" },
        proposed.slice(0, 4).map((r) => {
          const about = competitorsIn(r, names);
          return h(
            "a",
            { class: "row", href: `#/plays?focus=${r.id}` },
            h("span", { class: "prio-num" }, r.priority.toFixed(1)),
            h("span", { class: "row-main" }, h("span", { class: "row-title" }, r.action), about.length ? h("span", { class: "row-sub" }, `About ${about.join(", ")}`) : null),
          );
        }),
      )
    : empty("Nothing waiting for review. Run scout recommend.");

  const costsUs = deals.competitors.length
    ? h(
        "div",
        { class: "rows" },
        [...deals.competitors]
          .sort((a, b) => b.lost + b.open - (a.lost + a.open))
          .map((c) =>
            h(
              "a",
              { class: "row wl", href: hashFor(c.competitor) },
              h(
                "span",
                { class: "row-main" },
                h("span", { class: "wl-top" }, comp(c.competitor, false), h("span", { class: "wl-rate" }, `${pct(c.win_rate)} won`)),
                h(
                  "span",
                  { class: "wl-bar", role: "img", "aria-label": `${c.won} won, ${c.lost} lost` },
                  c.won + c.lost ? [h("span", { class: "won", style: `flex:${c.won}` }), h("span", { class: "lost", style: `flex:${c.lost}` })] : null,
                ),
                h("span", { class: "row-sub" }, `${c.won} won, ${c.lost} lost, ${c.open} open · ${compactMoney(c.amount_lost)} lost`),
              ),
            ),
          ),
      )
    : empty("No competitive deals loaded. Run scout load.");

  const latest = briefs[0];
  render(
    h(
      "div",
      { class: "intro" },
      h(
        "div",
        { class: "intro-text" },
        h("p", { class: "kicker" }, `Week of ${day(new Date().toISOString().slice(0, 10))}`),
        h("h1", { class: "headline" }, "Where myLIMS stands ", h("em", {}, "against the market")),
        story,
        h(
          "div",
          { class: "stats" },
          stat(won + lost ? pct(won / (won + lost)) : "–", `win rate vs competitors`),
          stat(int.format(open), "competitive deals open"),
        ),
      ),
      orbitBox,
    ),
    h(
      "div",
      { class: "columns" },
      h(
        "div",
        {},
        section("What they're doing", null, h("a", { class: "more", href: "#/signals" }, "All signals"), theirMoves),
        section("What we can do", "Plays waiting for approval, highest priority first.", h("a", { class: "more", href: "#/plays" }, "All plays"), ourPlays),
      ),
      h(
        "div",
        {},
        section("Where it costs us", `Deals against each competitor in ${deals.year}.`, null, costsUs),
        latest &&
          section(
            "Weekly briefing",
            null,
            null,
            h(
              "div",
              { class: "rows" },
              h(
                "a",
                { class: "row", href: `#/briefings?id=${latest.id}` },
                h("span", { class: "row-main" }, h("span", { class: "row-title" }, latest.title), h("span", { class: "row-sub" }, `${day(latest.report_date)} · ${latest.signal_count} signals`)),
                h("span", { class: "row-end" }, "Read"),
              ),
            ),
          ),
      ),
    ),
    section("Competitors", null, h("a", { class: "more", href: "#/competitors" }, "Head-to-head"), competitorGrid(competitors, deals, recs)),
  );
  drawOrbit(orbitBox, competitors, deals);
}

// The landscape as an orbit around myLIMS: the closer a competitor sits, the more deals
// it takes from us; the bigger its dot, the more deals are still open against it.
function drawOrbit(container, competitors, deals) {
  orbit(container, {
    center: "myLIMS",
    items: competitors.map((c) => {
      const d = deals.competitors.find((x) => x.competitor === c.name);
      const closed = d ? d.won + d.lost : 0;
      return {
        name: c.name,
        color: compColor(c.name),
        // 0 = we always lose (inner ring), 1 = we always win; not met yet sits outside
        closeness: closed ? d.win_rate : null,
        size: d ? d.open : 0,
        detail: d ? `${pct(d.win_rate)} won · ${d.open} open` : "No deals yet",
        fresh: c.signals_last_7_days,
        href: hashFor(c.name),
      };
    }),
  });
}

function competitorGrid(competitors, deals, recs) {
  const names = competitors.map((c) => c.name);
  return h(
    "div",
    { class: "rows comp-list" },
    h(
      "div",
      { class: "comp-row comp-row-head" },
      h("span", {}, "Competitor"),
      h("span", { class: "why-col" }, "Why we watch them"),
      h("span", { class: "num" }, "Win rate"),
      h("span", { class: "num" }, "Open"),
      h("span", { class: "num" }, "Plays"),
    ),
    competitors.map((c) => {
      const d = deals.competitors.find((x) => x.competitor === c.name);
      const plays = recs.filter((r) => r.status !== "rejected" && competitorsIn(r, names).includes(c.name)).length;
      const profile = PROFILES[c.name];
      return h(
        "a",
        { class: "comp-row", href: hashFor(c.name) },
        h(
          "span",
          { class: "comp-name" },
          comp(c.name, false),
          h("span", { class: "tag" }, c.tier === "top3" ? "Top 3" : "Watchlist"),
          c.signals_last_7_days ? h("span", { class: "tag new" }, `${c.signals_last_7_days} new`) : null,
        ),
        h("span", { class: "why-col" }, profile ? profile.why : ""),
        h("span", { class: "num" }, d ? pct(d.win_rate) : "–"),
        h("span", { class: "num" }, d ? int.format(d.open) : "–"),
        h("span", { class: "num" }, plays ? int.format(plays) : "–"),
      );
    }),
  );
}

// --- competitors ---

async function competitors(params, name) {
  if (name) return battlecard(name);
  crumbs(["Competitors"]);
  const [list, deals, recs] = await Promise.all([
    api("/competitors"),
    api(`/deals/competition${query({ year: params.get("year") })}`),
    api("/recommendations"),
  ]);
  setPlaysCount(recs);
  const chart = h("div");
  const orbitBox = h("div", { class: "orbit" });
  render(
    h(
      "div",
      { class: "intro" },
      h(
        "div",
        { class: "intro-text" },
        h("h1", { class: "headline" }, "Who we meet, ", h("em", {}, "and how it goes")),
        h("p", { class: "story" }, "The closer a competitor orbits myLIMS, the more deals it takes from us. Bigger dots have more deals still open: that is where a battlecard pays off first."),
        h("p", { class: "note" }, "Positioning comes from public research; deals and plays from Scout AI."),
      ),
      orbitBox,
    ),
    competitorGrid(list, deals, recs),
    section(
      "Head-to-head",
      `Deals closed in ${deals.year} where a competitor was involved, and deals open now.`,
      deals.years.length > 1 ? select("Year", deals.years.map((y) => [String(y), String(y)]).reverse(), String(deals.year), (v) => (location.hash = `#/competitors?year=${v}`)) : null,
      deals.competitors.length ? chart : empty("No competitive deals loaded. Run scout load."),
      dataTable({
        sortKey: "lost",
        columns: [
          { key: "competitor", label: "Competitor", format: (v) => comp(v) },
          {
            key: "record",
            label: "Record",
            sortable: false,
            cell: (c) =>
              h("span", { class: "wl-bar inline", title: `${c.won} won, ${c.lost} lost` }, c.won + c.lost ? [h("span", { class: "won", style: `flex:${c.won}` }), h("span", { class: "lost", style: `flex:${c.lost}` })] : null),
          },
          { key: "won", label: "Won", num: true },
          { key: "lost", label: "Lost", num: true, bar: "--lost" },
          { key: "win_rate", label: "Win rate", num: true, format: pct, bar: "--won" },
          { key: "open", label: "Open now", num: true, bar: "--accent" },
          { key: "amount_won", label: "Amount won", num: true, format: (v) => money.format(v) },
          { key: "amount_lost", label: "Amount lost", num: true, format: (v) => money.format(v), bar: "--lost" },
        ],
        rows: deals.competitors,
        note: "Click a column to sort. Amounts count only deals with a known amount.",
      }),
    ),
  );
  drawOrbit(orbitBox, list, deals);
  if (deals.competitors.length)
    stackedBars(chart, {
      title: `Deals closed in ${deals.year}`,
      segments: [
        { name: "Won", color: "--won" },
        { name: "Lost", color: "--lost" },
      ],
      rows: deals.competitors.map((c) => ({ label: c.competitor, parts: [c.won, c.lost] })),
    });
}

async function battlecard(name) {
  const [list, signalsList, deals, recs] = await Promise.all([
    api("/competitors"),
    api(`/signals${query({ competitor: name, limit: 50 })}`),
    api("/deals/competition"),
    api("/recommendations"),
  ]);
  setPlaysCount(recs);
  const c = list.find((x) => x.name === name);
  crumbs(["Competitors", "#/competitors"], [name]);
  if (!c) return render(head(null, "Competitor not found", `No competitor named “${name}”.`));
  const names = list.map((x) => x.name);
  const profile = PROFILES[name] || { why: null, angles: [] };
  const d = deals.competitors.find((x) => x.competitor === name);
  const plays = recs.filter((r) => competitorsIn(r, names).includes(name)).sort((a, b) => b.priority - a.priority);
  const color = compColor(name);

  const value = (text, cls) => (text ? h("td", { class: cls }, text) : h("td", { class: `${cls || ""} unknown` }, "Not researched yet"));
  const vs = h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      { class: "vs" },
      h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", { class: "us" }, "myLIMS ", h("span", {}, "(us)")), h("th", {}, name))),
      h(
        "tbody",
        {},
        DIMENSIONS.map(([key, title]) => h("tr", { class: key === "weakness" ? "weak" : null }, h("th", {}, title), value(MYLIMS[key], "us"), value(profile[key]))),
      ),
    ),
  );

  const dealTiles = d
    ? h(
        "div",
        { class: "tiles" },
        [
          ["Win rate", pct(d.win_rate)],
          ["Won / lost", `${d.won} / ${d.lost}`],
          ["Open now", int.format(d.open)],
          ["Amount lost", compactMoney(d.amount_lost)],
        ].map(([l, v]) => h("div", { class: "tile" }, h("div", { class: "label" }, l), h("div", { class: "value" }, v))),
      )
    : empty(`No deals against ${name} in HubSpot yet.`);

  const timeline = signalsList.length
    ? h(
        "div",
        { class: "timeline", style: `--c:${color}` },
        signalsList.map((s) =>
          h(
            "div",
            { class: "tl-item" },
            h("div", { class: "meta" }, h("span", { class: "chip" }, label(s.type)), day(s.detected_at)),
            h("h3", {}, link(s.url, s.title)),
            h("p", { class: "note", style: "color:var(--ink-2)" }, s.summary),
            s.relevance && h("div", { class: "why-box" }, h("strong", {}, "Why it matters: "), s.relevance),
          ),
        ),
      )
    : empty(c.website ? "No changes detected on their sites yet." : "Not collected.");

  const angles = h(
    "div",
    { class: "card angles" },
    h("h3", {}, "Angles to test"),
    profile.angles.length
      ? profile.angles.map((a) => h("div", { class: "angle" }, h("span", { class: "angle-icon" }), h("div", {}, a)))
      : h("p", { class: "empty" }, "No angle researched yet."),
    profile.links && h("div", { class: "actions" }, profile.links.map(([t, u]) => h("a", { class: "btn", href: u, target: "_blank", rel: "noopener noreferrer" }, t, " ↗"))),
    h("p", { class: "note" }, "Hypotheses from public positioning research (README §3), not from collected data."),
  );

  render(
    h(
      "div",
      { class: "page-head" },
      h(
        "div",
        { class: "bc-head" },
        h("div", { class: "bc-avatar", style: `--c:${color}` }, name.slice(0, 2)),
        h("div", {}, h("h1", {}, `myLIMS vs ${name}`), h("div", { class: "meta" }, h("span", { class: "tag" }, c.tier === "top3" ? "Top 3" : "Watchlist"), c.website && link(c.website, c.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")))),
      ),
      profile.why && h("p", { class: "lead" }, profile.why),
    ),
    section("Them vs us", "Where we stand on each dimension. The last row is where to push.", null, vs),
    section(
      "What we can do",
      "Plays Scout AI proposed with evidence about this competitor, and angles to test.",
      null,
      h("div", { class: "two-col" }, h("div", { class: "stack" }, plays.length ? plays.map(playCard) : empty(`No play mentions ${name} yet. Run scout recommend after new signals.`)), angles),
    ),
    section("Where we meet them", `Deals in ${deals.year} with ${name} involved.`, null, dealTiles),
    section("What they're doing", "Every meaningful change Scout AI found on their sites, newest first.", h("a", { class: "more", href: `#/signals?competitor=${encodeURIComponent(name)}&days=all` }, "Open in signals"), timeline),
  );
}

// --- signals ---

async function signals(params) {
  crumbs(["Signals"]);
  const competitor = params.get("competitor") || "";
  const type = params.get("type") || "";
  const days = params.get("days") || "30";
  const since = days === "all" ? null : new Date(Date.now() - Number(days) * 864e5).toISOString().slice(0, 10);
  const [list, items] = await Promise.all([api("/competitors"), api(`/signals${query({ competitor, type, since })}`)]);
  const go = (changes) => (location.hash = `#/signals${query({ competitor, type, days, ...changes })}`);
  const byDay = new Map();
  for (const s of items) {
    const key = day(s.detected_at);
    if (!byDay.has(key)) byDay.set(key, []);
    byDay.get(key).push(s);
  }
  render(
    head("Market", "Competitor signals", "Meaningful changes on competitor websites, found and summarized by the LLM. These are real, not demo data."),
    h(
      "div",
      { class: "filters" },
      segmented("Period", [["7", "7 days"], ["30", "30 days"], ["90", "90 days"], ["all", "All"]], days, (v) => go({ days: v })),
      segmented(
        "Competitor",
        [["", "All"], ...list.map((c) => [c.name, c.name, h("span", { class: "dot", style: `--c:${compColor(c.name)}` })])],
        competitor,
        (v) => go({ competitor: v }),
      ),
      select("Type", [["", "All types"], ...meta.signal_types.map((t) => [t, capital(label(t))])], type, (v) => go({ type: v })),
    ),
    items.length
      ? [...byDay].map(([d, group]) =>
          h(
            "div",
            {},
            h("div", { class: "tl-day" }, d),
            h(
              "div",
              { class: "rows", style: "margin-bottom:24px" },
              group.map((s) =>
                h(
                  "article",
                  { class: "signal", style: `--c:${compColor(s.competitor)}` },
                  h("div", { class: "meta" }, comp(s.competitor), h("span", { class: "chip" }, label(s.type))),
                  h("h3", { style: "margin-top:8px" }, link(s.url, s.title)),
                  h("p", {}, s.summary),
                  s.relevance && h("div", { class: "why-box" }, h("strong", {}, "What it means for us: "), s.relevance),
                ),
              ),
            ),
          ),
        )
      : empty("No signals for these filters. Try a longer period."),
  );
}

// --- plays (recommendations) ---

function score(name, value, lowerIsBetter) {
  return h(
    "div",
    { class: `score${lowerIsBetter ? " lower" : ""}` },
    h("div", { class: "top" }, h("span", {}, name), h("span", {}, `${value}/5`)),
    h("div", { class: "pips", "aria-label": `${name} ${value} of 5` }, [1, 2, 3, 4, 5].map((i) => h("i", { class: i <= value ? "on" : null }))),
  );
}

function evidenceList(evidence) {
  return h(
    "details",
    { class: "evidence" },
    h("summary", {}, `Evidence (${evidence.length})`),
    h(
      "ul",
      {},
      evidence.map((item) =>
        h(
          "li",
          {},
          item.kind && h("div", { class: "kind" }, label(item.kind)),
          h("strong", {}, link(item.url, item.label)),
          h("div", {}, item.note),
        ),
      ),
    ),
  );
}

function dryRun(result) {
  const task = result.clickup_task;
  return h(
    "div",
    { class: "dry-run" },
    h("div", { class: "dry-run-head" }, "Dry run · nothing was sent to ClickUp or HubSpot"),
    h(
      "div",
      { class: "dry-run-body" },
      h("div", { class: "meta" }, "ClickUp task that would be created"),
      h("h3", {}, task.name),
      h("div", { class: "meta", style: "margin-top:6px" }, task.tags.map((t) => h("span", { class: "chip" }, t))),
      h("pre", {}, task.markdown_description),
      h(
        "p",
        { class: "note" },
        result.hubspot_tags.length
          ? `HubSpot campaigns that would be tagged: ${result.hubspot_tags.map((t) => `${t.campaign} (${t.tag})`).join("; ")}`
          : "No campaign in the evidence: no HubSpot tag.",
      ),
    ),
  );
}

let competitorNames = [];

function playCard(rec, rank) {
  const card = h("article", { class: "card play", id: `play-${rec.id}` });
  const fill = (result) => {
    const r = result ? result.recommendation : rec;
    const about = competitorsIn(r, competitorNames);
    card.replaceChildren(
      h(
        "div",
        { class: "prio" },
        h("div", { class: "n" }, r.priority.toFixed(1)),
        h("div", { class: "l" }, "priority"),
      ),
      h(
        "div",
        {},
        h("div", { class: "meta" }, h("span", { class: `chip ${r.status}` }, r.status), about.map((n) => comp(n)), `Play ${r.id} · ${day(r.created_at)}`),
        h("h3", {}, r.action),
        h("div", { class: "scores" }, score("Impact", r.impact), score("Confidence", r.confidence), score("Cost", r.cost, true), score("Effort", r.effort, true)),
        evidenceList(r.evidence),
        r.status === "proposed" &&
          h(
            "div",
            { class: "actions" },
            h("button", { class: "btn primary", onclick: () => review(r.id, "approved") }, "Approve and create task"),
            h("button", { class: "btn ghost-danger", onclick: () => review(r.id, "rejected") }, "Reject"),
          ),
        result && result.clickup_task && dryRun(result),
      ),
    );
  };
  const review = async (id, status) => {
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    try {
      fill(await api(`/recommendations/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }));
      api("/recommendations").then(setPlaysCount).catch(() => {});
    } catch (error) {
      card.lastChild.append(h("p", { class: "error" }, error.message));
      card.querySelectorAll("button").forEach((b) => (b.disabled = false));
    }
  };
  fill(null);
  return card;
}

async function plays(params) {
  crumbs(["Plays"]);
  const status = params.get("status") ?? "proposed";
  const [all, list] = await Promise.all([api("/recommendations"), api("/competitors")]);
  competitorNames = list.map((c) => c.name);
  setPlaysCount(all);
  const shown = all.filter((r) => !status || r.status === status).sort((a, b) => b.priority - a.priority);
  const countOf = (s) => all.filter((r) => r.status === s).length;
  render(
    head(
      "Act",
      "Plays",
      "What we can do next, ranked by priority = impact × confidence ÷ (cost + effort), computed in code. Each cites evidence checked against stored data. Built on the synthetic demo data: they show how the system works, not what the business should do.",
    ),
    h(
      "div",
      { class: "filters" },
      segmented(
        "Status",
        [["proposed", `To review (${countOf("proposed")})`], ["approved", `Approved (${countOf("approved")})`], ["rejected", `Rejected (${countOf("rejected")})`], ["", `All (${all.length})`]],
        status,
        (v) => (location.hash = `#/plays?status=${v}`),
      ),
    ),
    shown.length ? h("div", { class: "stack" }, shown.map((r, i) => playCard(r, i))) : empty(status === "proposed" ? "Nothing waiting for review. Run scout recommend." : "No plays here."),
  );
  const focus = params.get("focus");
  if (focus) document.getElementById(`play-${focus}`)?.scrollIntoView({ block: "center" });
}

// --- funnel ---

function previousMonth(iso) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCMonth(d.getUTCMonth() - 1);
  return d.toISOString().slice(0, 10);
}

async function funnel(params) {
  crumbs(["Funnel"]);
  if (!meta.months.length) return render(head("Our numbers", "Funnel"), empty("No internal data. Run scout load."));
  const month = params.get("month") || meta.latest_spend_month || meta.months.at(-1);
  const by = params.get("by") || "region";
  const before = previousMonth(month);
  const [groups, totals] = await Promise.all([
    api(`/funnel${query({ by, to: month })}`),
    api(`/funnel${query({ by: "total", to: meta.latest_spend_month })}`),
  ]);
  const sum = (period, f) => groups.filter((r) => r.period === period).reduce((a, r) => a + r[f], 0);
  const periods = [...new Set(groups.map((r) => r.period))].sort().slice(-12);

  const names = [...new Set(groups.map((r) => r.group))];
  const index = new Map(groups.map((r) => [`${r.group}|${r.period}`, r]));
  const get = (group, period) => index.get(`${group}|${period}`) || { mqls: 0, opportunities: 0, deals_won: 0 };
  const rows = names
    .map((name) => {
      const now = get(name, month), prev = get(name, before);
      return {
        name,
        trend: periods.map((p) => get(name, p).mqls),
        mqls: now.mqls,
        mqls_before: prev.mqls,
        opportunities: now.opportunities,
        opportunities_before: prev.opportunities,
        deals_won: now.deals_won,
        deals_won_before: prev.deals_won,
        conversion: now.mqls ? now.opportunities / now.mqls : null,
        conversion_before: prev.mqls ? prev.opportunities / prev.mqls : null,
      };
    })
    .filter((r) => r.mqls || r.mqls_before || r.opportunities || r.deals_won)
    .sort((a, b) => b.mqls - a.mqls)
    .slice(0, by === "campaign" ? 25 : undefined);

  const shape = h("div");
  const trend = h("div");
  const trend2 = h("div");
  const go = (changes) => (location.hash = `#/funnel${query({ month, by, ...changes })}`);
  render(
    head(
      "Our numbers",
      "Funnel",
      `${monthName(month)} against ${monthName(before)}. Leads and SQLs are not tracked yet, so the funnel starts at MQLs. Charts end at the latest month with Marketing spend, the last complete month of the exports.`,
    ),
    h(
      "div",
      { class: "filters" },
      select("Month", meta.months.map((m) => [m, monthName(m)]).reverse(), month, (v) => go({ month: v })),
      segmented("Group by", [["region", "Region"], ["channel", "Channel"], ["campaign", "Campaign"]], by, (v) => go({ by: v })),
    ),
    shape,
    h("div", { class: "charts-2" }, trend, trend2),
    section(
      `By ${by}`,
      `Trend shows MQLs over the last ${periods.length} months. Arrows compare with ${monthName(before)}.`,
      null,
      dataTable({
        sortKey: "mqls",
        columns: [
          { key: "name", label: capital(by) },
          { key: "trend", label: "Trend", spark: "trend" },
          { key: "mqls", label: "MQLs", num: true, format: (v) => int.format(v), delta: "mqls_before", bar: "--series-1" },
          { key: "opportunities", label: "Opportunities", num: true, format: (v) => int.format(v), delta: "opportunities_before", bar: "--series-5" },
          { key: "deals_won", label: "Deals won", num: true, format: (v) => int.format(v), delta: "deals_won_before" },
          { key: "conversion", label: "MQL to opp.", num: true, format: pct, delta: "conversion_before", bar: "--series-2" },
        ],
        rows,
        note: by === "campaign" ? "Top 25 campaigns by MQLs in the month. Click a column to sort." : "Click a column to sort.",
      }),
    ),
  );
  funnelShape(shape, {
    compare: `vs ${monthName(before).split(" ")[0]}`,
    format: (v) => int.format(v),
    stages: [
      { name: "MQLs", value: sum(month, "mqls"), before: sum(before, "mqls") },
      { name: "Opportunities", value: sum(month, "opportunities"), before: sum(before, "opportunities") },
      { name: "Deals won", value: sum(month, "deals_won"), before: sum(before, "deals_won") },
    ],
  });
  const totalPeriods = totals.map((r) => r.period);
  lineChart(trend, {
    title: "MQLs per month, all regions",
    xLabels: totalPeriods.map(monthName),
    series: [{ name: "MQLs", color: SERIES[0], values: totals.map((r) => r.mqls) }],
    format: (v) => int.format(Math.round(v)),
  });
  lineChart(trend2, {
    title: "Opportunities and deals won per month",
    xLabels: totalPeriods.map(monthName),
    series: [
      { name: "Opportunities", color: SERIES[0], values: totals.map((r) => r.opportunities) },
      { name: "Deals won", color: SERIES[1], values: totals.map((r) => r.deals_won) },
    ],
    format: (v) => int.format(Math.round(v)),
  });
}

// --- spend ---

const METRICS = {
  spend: ["Spend", (v, axis) => (axis ? compactMoney(v) : money.format(v)), false],
  cost_per_mql: ["Cost per MQL", (v) => money.format(v), true],
  opportunities_per_1k: ["Opps per $1,000", (v) => v.toFixed(1), false],
  cac: ["Marketing CAC", (v, axis) => (axis ? compactMoney(v) : money.format(v)), true],
};

async function spend(params) {
  crumbs(["Spend"]);
  const metric = params.get("metric") || "cost_per_mql";
  const region = params.get("region") || "";
  const rows = await api(`/spend${query({ region })}`);
  if (!rows.length) return render(head("Our numbers", "Spend per region"), empty("No Marketing spend loaded. Run scout load."));
  const periods = [...new Set(rows.map((r) => r.period))].sort();
  const regions = [...new Set(rows.map((r) => r.region))];
  const order = meta.regions.map((r) => r.value).filter((r) => regions.includes(r));
  const colorOf = (value) => SERIES[meta.regions.findIndex((r) => r.value === value) % SERIES.length]; // color follows the region
  const chart = h("div");
  const [name, format, lowerIsBetter] = METRICS[metric];
  const latest = periods.at(-1);
  const previous = periods.at(-2);
  const go = (changes) => (location.hash = `#/spend${query({ metric, region, ...changes })}`);
  const at = (period) => rows.filter((r) => r.period === period);
  const totalsOf = (period) => {
    const list = at(period);
    const total = list.reduce((a, r) => a + r.spend, 0);
    const won = list.reduce((a, r) => a + r.deals_won, 0);
    const mqls = list.reduce((a, r) => a + r.mqls, 0);
    return { total, perMql: mqls ? total / mqls : null, cac: won ? total / won : null };
  };
  const now = totalsOf(latest), prev = previous ? totalsOf(previous) : {};
  const tile = (labelText, value, before, fmt, lower) =>
    h("div", { class: "tile" }, h("div", { class: "label" }, labelText), h("div", { class: "value" }, value == null ? "–" : fmt(value)), value != null && before ? delta(value, before, { upIsGood: lower == null ? null : !lower }) : null);

  const tableRows = order.map((value) => {
    const r = at(latest).find((x) => x.region === value) || { region_label: meta.regions.find((x) => x.value === value).label };
    const p = previous ? at(previous).find((x) => x.region === value) || {} : {};
    return {
      region: value,
      region_label: r.region_label,
      trend: periods.map((period) => rows.find((x) => x.period === period && x.region === value)?.[metric] ?? null),
      spend: r.spend ?? null,
      spend_before: p.spend ?? null,
      mqls: r.mqls ?? null,
      opportunities: r.opportunities ?? null,
      deals_won: r.deals_won ?? null,
      cost_per_mql: r.cost_per_mql ?? null,
      cost_per_mql_before: p.cost_per_mql ?? null,
      opportunities_per_1k: r.opportunities_per_1k ?? null,
      opportunities_per_1k_before: p.opportunities_per_1k ?? null,
      cac: r.cac ?? null,
      cac_before: p.cac ?? null,
    };
  });

  render(
    head(
      "Our numbers",
      "Spend per region",
      "Spend is only known per region. Pipeline value per dollar needs opportunity amounts, which are not stored, so opportunities per $1,000 stand in for it. Marketing CAC is spend per deal won.",
    ),
    h(
      "div",
      { class: "filters" },
      segmented("Metric", Object.entries(METRICS).map(([k, [n]]) => [k, n]), metric, (v) => go({ metric: v })),
      select("Region", [["", "All regions"], ...meta.regions.filter((r) => regions.includes(r.value) || r.value === region).map((r) => [r.value, r.label])], region, (v) => go({ region: v })),
    ),
    h(
      "div",
      { class: "tiles" },
      tile(`Spend, ${monthName(latest)}`, now.total, prev.total, (v) => money.format(v), null),
      tile("Cost per MQL", now.perMql, prev.perMql, (v) => money.format(v), true),
      tile("Marketing CAC", now.cac, prev.cac, (v) => money.format(v), true),
    ),
    chart,
    section(
      monthName(latest),
      `Trend shows ${name.toLowerCase()} per month. Arrows compare with ${previous ? monthName(previous) : "the month before"}; for costs, down is good.`,
      null,
      dataTable({
        sortKey: "spend",
        columns: [
          { key: "region_label", label: "Region", format: (v, row) => h("span", { class: "comp" }, h("span", { class: "dot", style: `--c:var(${colorOf(row.region)})` }), v) },
          { key: "trend", label: name, spark: "trend" },
          { key: "spend", label: "Spend", num: true, format: (v) => money.format(v), delta: "spend_before", neutral: true, bar: "--series-1" },
          { key: "mqls", label: "MQLs", num: true, format: (v) => int.format(v) },
          { key: "opportunities", label: "Opps", num: true, format: (v) => int.format(v) },
          { key: "deals_won", label: "Won", num: true, format: (v) => int.format(v) },
          { key: "cost_per_mql", label: "Cost per MQL", num: true, format: (v) => money.format(v), delta: "cost_per_mql_before", lowerIsBetter: true, bar: "--series-2" },
          { key: "opportunities_per_1k", label: "Opps per $1k", num: true, format: (v) => v.toFixed(1), delta: "opportunities_per_1k_before" },
          { key: "cac", label: "Marketing CAC", num: true, format: (v) => money.format(v), delta: "cac_before", lowerIsBetter: true, bar: "--lost" },
        ],
        rows: tableRows,
        note: "A dash means the ratio has no denominator that month (no MQLs or no deals won). Click a column to sort.",
      }),
    ),
  );
  lineChart(chart, {
    title: `${name} per month${lowerIsBetter ? " (lower is better)" : ""}`,
    xLabels: periods.map(monthName),
    series: order.map((value) => ({
      name: meta.regions.find((r) => r.value === value).label,
      color: colorOf(value),
      values: periods.map((p) => rows.find((r) => r.period === p && r.region === value)?.[metric] ?? null),
    })),
    format,
  });
}

// --- weekly briefings (notifications) ---

async function briefings(params) {
  crumbs(["Weekly briefings"]);
  const list = await refreshBadge();
  if (!list.length) return render(head("Act", "Weekly briefings"), empty("No weekly summary yet. Run scout report."));
  markSeen(list[0].id);
  const selected = Number(params.get("id")) || list[0].id;
  const summary = await api(`/notifications/${selected}`);
  const body = h("div", { class: "markdown" });
  body.innerHTML = renderMarkdown(summary.markdown); // escaped by the renderer
  render(
    head("Act", "Weekly briefings", "Competitor moves, our numbers and the plays of the week, newest first."),
    h(
      "div",
      { class: "split" },
      h(
        "div",
        { class: "list" },
        list.map((item) =>
          h(
            "button",
            { "aria-current": item.id === selected ? "true" : null, onclick: () => (location.hash = `#/briefings?id=${item.id}`) },
            h("div", { class: "meta" }, h("strong", { style: "color:var(--ink)" }, day(item.report_date)), item.id === list[0].id ? h("span", { class: "chip proposed" }, "latest") : null),
            h("div", { class: "meta" }, `${item.signal_count} signals`),
          ),
        ),
      ),
      body,
    ),
  );
}

// --- router ---

const VIEWS = { overview, competitors, signals, plays, funnel, spend, briefings };
const ALIASES = { notifications: "briefings", recommendations: "plays", deals: "competitors" };

async function route() {
  const [path, search] = location.hash.replace(/^#\/?/, "").split("?");
  const [first, ...rest] = path.split("/");
  const name = VIEWS[first] ? first : ALIASES[first] || "overview";
  const sub = rest.length ? decodeURIComponent(rest.join("/")) : null;
  document.querySelectorAll("#nav a").forEach((a) => a.setAttribute("aria-current", a.dataset.view === name ? "page" : "false"));
  view.style.opacity = "0.4";
  try {
    meta = meta || (await api("/meta"));
    document.getElementById("banner").textContent = meta.banner;
    if (!competitorNames.length) competitorNames = (await api("/competitors")).map((c) => c.name);
    await VIEWS[name](new URLSearchParams(search || ""), sub);
    if (name !== "briefings" && name !== "overview") refreshBadge().catch(() => {});
    if (name !== "plays" && name !== "overview" && name !== "competitors") api("/recommendations").then(setPlaysCount).catch(() => {});
  } catch (error) {
    render(head(null, "Something went wrong"), h("p", { class: "error" }, error.message));
  } finally {
    view.style.opacity = "";
  }
  if (!new URLSearchParams(search || "").get("focus")) window.scrollTo(0, 0);
}

window.addEventListener("hashchange", route);
route();
