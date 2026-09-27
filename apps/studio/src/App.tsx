import { useEffect, useRef, useState } from "react";
import { createModel, runScenario, type Report, type SimEvent } from "./api";
import { MODEL, SCENARIOS } from "./fixtures";
import { activeFaults, failuresUpTo, renderGraph } from "./graph";
import type cytoscape from "cytoscape";

export const DEFAULT_API_BASE = "https://shadowbox-api.pablodo004.workers.dev";

export default function App() {
  const [base, setBase] = useState(DEFAULT_API_BASE);
  const [scenarioName, setScenarioName] = useState("db-down");
  const [baseline, setBaseline] = useState<Report | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [events, setEvents] = useState<SimEvent[]>([]);
  const [t, setT] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  const scenario = SCENARIOS.find((s) => s.name === scenarioName) ?? SCENARIOS[0];

  async function run() {
    setBusy(true);
    setError("");
    try {
      const modelId = await createModel(base, MODEL);
      const baseRes = await runScenario(base, modelId, SCENARIOS[0], 42);
      const cur = await runScenario(base, modelId, scenario, 42);
      setBaseline(baseRes.report);
      setReport(cur.report);
      setEvents(cur.events);
      setT(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!boxRef.current || !report) return;
    cyRef.current?.destroy();
    const timeouts: Record<string, number> = {};
    for (const [id, c] of Object.entries(report.metrics.components)) timeouts[id] = c.timeouts;
    cyRef.current = renderGraph(boxRef.current, MODEL.components, MODEL.connections, failuresUpTo(events, t * 1000), timeouts);
    return () => cyRef.current?.destroy();
  }, [report, events, t]);

  const m = report?.metrics;
  const verdict = baseline && m ? (m.error_rate > baseline.metrics.error_rate ? "REGRESSION" : "pass") : "-";

  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <h1>ShadowBox Studio</h1>
      <p>What-if simulation. Results are illustrative, never production measurements.</p>
      <label>API base <input value={base} onChange={(e) => setBase(e.target.value)} size={30} /></label>{" "}
      <button onClick={() => setBase("http://127.0.0.1:8000")}>use local</button>{" "}
      <label>Scenario{" "}
        <select value={scenarioName} onChange={(e) => setScenarioName(e.target.value)}>
          {SCENARIOS.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
        </select>
      </label>{" "}
      <button onClick={run} disabled={busy}>{busy ? "Running..." : "Run vs baseline"}</button>
      {error && <pre style={{ color: "red" }}>{error}</pre>}
      {m && (
        <>
          <p>error_rate={m.error_rate.toFixed(3)} p99={m.latency_ms.p99}ms verdict={verdict} hash={report?.metrics_hash.slice(0, 12)}</p>
          <div ref={boxRef} style={{ width: "100%", height: 320, border: "1px solid #ccc" }} />
          <label>t={t}s <input type="range" min={0} max={scenario.duration_s} value={t} onChange={(e) => setT(Number(e.target.value))} /></label>
          <pre>active_faults=[{activeFaults(scenario.faults, t).join(", ") || "none"}]</pre>
        </>
      )}
    </main>
  );
}
