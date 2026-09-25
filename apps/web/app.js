// M4b static demo: baseline vs db-down on the bundled checkout model.
const MODEL = {
  components: [
    { id: "api", type: "service", capacity: 50, latency_ms: { base: 20, jitter_ms: 5 }, timeout_ms: 1000, queue_size: 200, queue_policy: "drop" },
    { id: "cache", type: "cache", capacity: 100, latency_ms: { base: 2, jitter_ms: 1 }, timeout_ms: 200, queue_size: 500, queue_policy: "drop" },
    { id: "database", type: "database", capacity: 20, latency_ms: { base: 5, jitter_ms: 1 }, timeout_ms: 500, queue_size: 100, queue_policy: "fifo" }
  ],
  connections: [
    { from: "api", to: "cache" },
    { from: "api", to: "database" },
    { from: "cache", to: "database" }
  ]
};

const BASELINE = { name: "baseline", duration_s: 60, workload: { rate_rps: 100 }, faults: [] };
const DB_DOWN = {
  name: "db-down", duration_s: 60, workload: { rate_rps: 100 },
  faults: [{ target: "database", type: "unavailable", start_s: 20, duration_s: 10 }]
};

async function post(base, path, body, query = "") {
  const res = await fetch(`${base}${path}${query}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

async function run(base, scenario) {
  const model = await post(base, "/api/v1/models", MODEL);
  const sim = await post(base, "/api/v1/simulations", { scenario, seed: 42 }, `?model_id=${model.id}`);
  const report = await (await fetch(`${base}/api/v1/simulations/${sim.id}/report`)).json();
  return { report, simId: sim.id };
}

let lastReport = null;
let lastEvents = [];
let lastScenario = DB_DOWN;

function drawGraph(model, failuresByComponent) {
  const svg = document.getElementById("graph");
  const NS = "http://www.w3.org/2000/svg";
  svg.replaceChildren();
  const defs = document.createElementNS(NS, "defs");
  defs.innerHTML = `<marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#888"/></marker>`;
  svg.appendChild(defs);
  const ids = model.components.map((c) => c.id);
  const pos = {};
  ids.forEach((id, i) => { pos[id] = { x: 90 + i * 250, y: 110 }; });
  model.connections.forEach((c) => {
    const a = pos[c.from], b = pos[c.to];
    if (!a || !b) return;
    const line = document.createElementNS(NS, "line");
    line.setAttribute("x1", a.x + 45); line.setAttribute("y1", a.y);
    line.setAttribute("x2", b.x - 50); line.setAttribute("y2", b.y);
    line.setAttribute("class", "edge");
    svg.appendChild(line);
  });
  model.components.forEach((c) => {
    const p = pos[c.id];
    const fails = failuresByComponent[c.id] || 0;
    const timeouts = (lastReport?.metrics.components[c.id]?.timeouts) || 0;
    const cls = fails > 0 ? "node-fail" : (timeouts > 0 ? "node-warn" : "node-ok");
    const g = document.createElementNS(NS, "g");
    g.innerHTML = `<circle cx="${p.x}" cy="${p.y}" r="42" class="${cls}"/>` +
      `<text x="${p.x}" y="${p.y - 2}" class="label">${c.id}</text>` +
      `<text x="${p.x}" y="${p.y + 16}" class="label">${c.type} fails:${fails}</text>`;
    svg.appendChild(g);
  });
}

function scrub(tSeconds) {
  if (!lastReport) return;
  const tMs = tSeconds * 1000;
  document.getElementById("tlabel").textContent = String(tSeconds);
  const done = lastEvents.filter((e) => e.finish_ms <= tMs);
  const failed = done.filter((e) => !e.ok);
  const byComponent = {};
  failed.forEach((e) => { byComponent[e.failed_at] = (byComponent[e.failed_at] || 0) + 1; });
  drawGraph(MODEL, byComponent);
  const faults = (lastScenario.faults || [])
    .filter((f) => f.start_s <= tSeconds && tSeconds < f.start_s + f.duration_s)
    .map((f) => `${f.type}@${f.target}`);
  document.getElementById("replay").textContent =
    `t=${tSeconds}s sampled=${done.length}/${lastEvents.length} ` +
    `failed=${failed.length} active_faults=[${faults.join(", ") || "none"}]`;
}

document.getElementById("time").addEventListener("input", (ev) => scrub(Number(ev.target.value)));

document.getElementById("run").addEventListener("click", async () => {
  const out = document.getElementById("out");
  const base = document.getElementById("api").value.replace(/\/$/, "");
  out.textContent = "Running...";
  try {
    const ra = await run(base, BASELINE);
    const rb = await run(base, DB_DOWN);
    const a = ra.report, b = rb.report;
    const ma = a.metrics, mb = b.metrics;
    out.textContent =
      `baseline: error_rate=${ma.error_rate.toFixed(3)} p99=${ma.latency_ms.p99}ms\n` +
      `db-down:  error_rate=${mb.error_rate.toFixed(3)} p99=${mb.latency_ms.p99}ms\n` +
      `verdict:  ${mb.error_rate > ma.error_rate ? "REGRESSION" : "pass"}\n` +
      `hash:     ${b.metrics_hash.slice(0, 12)} (seed 42, confidence ${b.confidence})`;
    lastReport = b;
    lastScenario = DB_DOWN;
    const ev = await (await fetch(`${base}/api/v1/simulations/${rb.simId}/events?limit=500`)).json();
    lastEvents = ev.events;
    const slider = document.getElementById("time");
    slider.max = String(DB_DOWN.duration_s);
    scrub(Number(slider.value));
  } catch (err) {
    out.textContent = `Error: ${err.message}\nIs the API running? uv run uvicorn shadowbox.api:app`;
  }
});
