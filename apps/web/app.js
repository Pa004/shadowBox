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
  return report;
}

document.getElementById("run").addEventListener("click", async () => {
  const out = document.getElementById("out");
  const base = document.getElementById("api").value.replace(/\/$/, "");
  out.textContent = "Running...";
  try {
    const a = await run(base, BASELINE);
    const b = await run(base, DB_DOWN);
    const ma = a.metrics, mb = b.metrics;
    out.textContent =
      `baseline: error_rate=${ma.error_rate.toFixed(3)} p99=${ma.latency_ms.p99}ms\n` +
      `db-down:  error_rate=${mb.error_rate.toFixed(3)} p99=${mb.latency_ms.p99}ms\n` +
      `verdict:  ${mb.error_rate > ma.error_rate ? "REGRESSION" : "pass"}\n` +
      `hash:     ${b.metrics_hash.slice(0, 12)} (seed 42, confidence ${b.confidence})`;
  } catch (err) {
    out.textContent = `Error: ${err.message}\nIs the API running? uv run uvicorn shadowbox.api:app`;
  }
});
