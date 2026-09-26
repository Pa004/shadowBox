export interface Latency {
  p50: number;
  p90: number;
  p95: number;
  p99: number;
}

export interface ComponentMetrics {
  utilization: number;
  queue_depth: number;
  timeouts: number;
}

export interface Metrics {
  throughput_rps: number;
  error_rate: number;
  latency_ms: Latency;
  timeouts: number;
  retries: number;
  cascade_depth: number;
  components: Record<string, ComponentMetrics>;
}

export interface Report {
  metrics: Metrics;
  metrics_hash: string;
  seed: number;
  confidence: string;
  calibration_source: string;
}

export interface SimEvent {
  correlation_id: string;
  ok: boolean;
  latency_ms: number;
  failed_at: string | null;
  timed_out: boolean;
  arrival_ms: number;
  finish_ms: number;
}

export interface Fault {
  target: string;
  type: string;
  start_s: number;
  duration_s: number;
  extra_ms?: number;
}

export interface Scenario {
  name: string;
  duration_s: number;
  workload: { rate_rps: number };
  faults: Fault[];
}

async function postJson(base: string, path: string, body: unknown, query = ""): Promise<unknown> {
  const res = await fetch(`${base}${path}${query}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json() as Promise<unknown>;
}

export async function createModel(base: string, model: unknown): Promise<string> {
  const out = (await postJson(base, "/api/v1/models", model)) as { id: string };
  return out.id;
}

export async function runScenario(
  base: string,
  modelId: string,
  scenario: Scenario,
  seed: number
): Promise<{ simId: string; report: Report; events: SimEvent[] }> {
  const sim = (await postJson(base, "/api/v1/simulations", { scenario, seed }, `?model_id=${modelId}`)) as {
    id: string;
  };
  const report = (await (await fetch(`${base}/api/v1/simulations/${sim.id}/report`)).json()) as Report;
  const page = (await (
    await fetch(`${base}/api/v1/simulations/${sim.id}/events?limit=500`)
  ).json()) as { events: SimEvent[] };
  return { simId: sim.id, report, events: page.events };
}
