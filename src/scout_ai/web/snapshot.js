// Static mode, for the GitHub Pages copy of the dashboard (`scout pages`): answers the front
// end's API calls from snapshot.json instead of the server. Approving a play shows the dry run
// precomputed at build time; approvals and rejections live only in this tab and are never saved.

let data = null;
const reviewed = new Map(); // recommendation id -> "approved" | "rejected"

async function load(file) {
  if (!data) {
    const response = await fetch(file);
    if (!response.ok) throw new Error(`Could not load the snapshot (${response.status})`);
    data = await response.json();
  }
  return data;
}

function recommendation(rec) {
  const status = reviewed.get(rec.id);
  if (status === "approved") return data.approvals[rec.id].recommendation;
  if (status === "rejected") return { ...rec, status: "rejected" };
  return rec;
}

function review(id, status) {
  const rec = data.recommendations.find((r) => r.id === id);
  if (!rec) throw new Error(`recommendation ${id} not found`);
  if (reviewed.has(id) || rec.status !== "proposed") throw new Error(`recommendation ${id} was already reviewed`);
  if (status === "approved" && !data.approvals[id]) throw new Error(`no dry run stored for recommendation ${id}`);
  reviewed.set(id, status);
  if (status === "approved") return data.approvals[id];
  return { recommendation: recommendation(rec), dry_run: true, clickup_task: null, hubspot_tags: [] };
}

export async function staticApi(file, path, options = {}) {
  await load(file);
  const url = new URL(path, "https://snapshot.invalid");
  const p = url.searchParams;
  const route = url.pathname;

  const item = /^\/recommendations\/(\d+)$/.exec(route);
  if (item && options.method === "PATCH") return review(Number(item[1]), JSON.parse(options.body).status);

  if (route === "/meta") {
    const built = new Date(data.built_at).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" });
    return { ...data.meta, banner: `${data.meta.banner} · snapshot from ${built}, approvals are not saved` };
  }
  if (route === "/competitors") return data.competitors;
  if (route === "/signals") {
    const since = p.get("since");
    return data.signals
      .filter((s) => (!p.get("competitor") || s.competitor === p.get("competitor")) && (!p.get("type") || s.type === p.get("type")) && (!since || s.detected_at.slice(0, 10) >= since))
      .slice(0, Number(p.get("limit") || 200));
  }
  if (route === "/funnel") {
    const from = p.get("from"), to = p.get("to");
    return (data.funnel[p.get("by") || "region"] || []).filter((r) => (!from || r.period >= from) && (!to || r.period <= to));
  }
  if (route === "/spend") return data.spend.filter((r) => !p.get("region") || r.region === p.get("region"));
  if (route === "/deals/competition") return data.deals[p.get("year")] || data.deals.default;
  if (route === "/recommendations") return data.recommendations.map(recommendation).filter((r) => !p.get("status") || r.status === p.get("status"));
  if (route === "/notifications") return data.notifications.map(({ markdown, ...rest }) => rest);
  const note = /^\/notifications\/(\d+)$/.exec(route);
  if (note) {
    const found = data.notifications.find((n) => n.id === Number(note[1]));
    if (!found) throw new Error(`summary ${note[1]} not found`);
    return found;
  }
  throw new Error(`${route} is not available in the static snapshot`);
}
