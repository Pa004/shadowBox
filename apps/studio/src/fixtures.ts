export const MODEL = {
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

export const SCENARIOS = [
  { name: "baseline", duration_s: 60, workload: { rate_rps: 100 }, faults: [] },
  { name: "db-down", duration_s: 60, workload: { rate_rps: 100 }, faults: [{ target: "database", type: "unavailable", start_s: 20, duration_s: 10 }] },
  { name: "cache-poison", duration_s: 60, workload: { rate_rps: 100 }, faults: [{ target: "cache", type: "unavailable", start_s: 20, duration_s: 10 }] },
  { name: "latency-500ms", duration_s: 60, workload: { rate_rps: 100 }, faults: [{ target: "database", type: "latency", extra_ms: 500, start_s: 0, duration_s: 60 }] },
  { name: "traffic-10x", duration_s: 60, workload: { rate_rps: 1000 }, faults: [] },
  { name: "zone-loss", duration_s: 60, workload: { rate_rps: 100 }, faults: [{ target: "cache", type: "unavailable", start_s: 20, duration_s: 20 }, { target: "database", type: "unavailable", start_s: 20, duration_s: 20 }] },
  { name: "slow-dependency", duration_s: 60, workload: { rate_rps: 100 }, faults: [{ target: "cache", type: "latency", extra_ms: 100, start_s: 0, duration_s: 60 }] },
  { name: "queue-overflow", duration_s: 10, workload: { rate_rps: 3000 }, faults: [] }
];
