import cytoscape from "cytoscape";
import type { SimEvent } from "./api";

export type NodeStatus = "ok" | "failing" | "degraded";

export function renderGraph(
  container: HTMLElement,
  components: { id: string; type: string }[],
  connections: { from: string; to: string }[],
  failures: Record<string, number>,
  timeouts: Record<string, number>
): cytoscape.Core {
  const nodes = components.map((c) => {
    const fails = failures[c.id] ?? 0;
    const status: NodeStatus = fails > 0 ? "failing" : (timeouts[c.id] ?? 0) > 0 ? "degraded" : "ok";
    return { data: { id: c.id, label: `${c.id}\n${c.type} fails:${fails}`, status } };
  });
  const edges = connections.map((c, i) => ({ data: { id: `e${i}`, source: c.from, target: c.to } }));
  return cytoscape({
    container,
    elements: [...nodes, ...edges],
    style: [
      {
        selector: "node",
        style: {
          label: "data(label)",
          color: "#fff",
          "font-family": "JetBrains Mono, ui-monospace, monospace",
          "text-valign": "center",
          "text-halign": "center",
          "font-size": "10px",
          "text-wrap": "wrap",
          "text-max-width": "78px",
          width: 88,
          height: 88
        }
      },
      { selector: 'node[status="ok"]', style: { "background-color": "oklch(74% 0.155 150)" } },
      { selector: 'node[status="failing"]', style: { "background-color": "oklch(70% 0.175 28)" } },
      { selector: 'node[status="degraded"]', style: { "background-color": "oklch(80% 0.14 82)" } },
      { selector: "edge", style: { width: 2, "line-color": "#888", "target-arrow-shape": "triangle", "target-arrow-color": "#888" } }
    ],
    layout: { name: "breadthfirst", directed: true, padding: 30 }
  });
}

export function failuresUpTo(events: SimEvent[], tMs: number): Record<string, number> {
  const out: Record<string, number> = {};
  for (const e of events) {
    if (e.finish_ms <= tMs && !e.ok && e.failed_at) out[e.failed_at] = (out[e.failed_at] ?? 0) + 1;
  }
  return out;
}

export function activeFaults(faults: { target: string; type: string; start_s: number; duration_s: number }[], tS: number): string[] {
  return faults
    .filter((f) => f.start_s <= tS && tS < f.start_s + f.duration_s)
    .map((f) => `${f.type}@${f.target}`);
}
