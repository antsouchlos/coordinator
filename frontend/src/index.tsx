import React, {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";
import { createRoot } from "react-dom/client";
import { useBridge } from "./bridge";
import { ResultsTree } from "./hierarchy";
import { PlotView } from "./plot";
import { defaults, parent, plural } from "./types";
import type {
  Kind,
  Model,
  PanelKind,
  Plot,
  Response,
  Run,
  Snapshot,
  Settings,
} from "./types";
import "./style.css";

function App({ model }: { model: Model }) {
  const rpc = useBridge(model);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [plot, setPlot] = useState<Plot | null>(null);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = snapshot?.generation ?? 0;
  const absorb = useCallback((response: Response) => {
    if (response.snapshot) setSnapshot(response.snapshot);
    else if (response.settings)
      setSnapshot((previous) =>
        previous
          ? {
              ...previous,
              settings: response.settings!,
              settings_error: response.settings_error || "",
            }
          : previous,
      );
    if (response.plot) setPlot(response.plot);
  }, []);
  useEffect(() => {
    let live = true;
    rpc("boot")
      .then((r) => {
        if (live) absorb(r);
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [rpc, absorb]);
  const action = useCallback(
    async (name: string, payload: Record<string, unknown> = {}) => {
      setError("");
      try {
        const r = await rpc(name, { ...payload, generation });
        absorb(r);
        return r;
      } catch (e) {
        setError((e as Error).message);
        throw e;
      }
    },
    [rpc, generation, absorb],
  );
  const plotKey = snapshot
    ? JSON.stringify([
        snapshot.generation,
        snapshot.settings.selected_runs,
        snapshot.settings.plot,
      ])
    : "";
  useEffect(() => {
    if (!snapshot) return;
    if (snapshot.settings.selected_runs.length === 0) {
      setPlot(null);
      return;
    }
    let live = true;
    const timer = window.setTimeout(() => {
      rpc("plot", { generation: snapshot.generation })
        .then((r) => {
          if (live) setPlot(r.plot || null);
        })
        .catch((e) => {
          if (live) setPlot({ metrics: [], figure: null, error: e.message });
        });
    }, 150);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [rpc, plotKey]);
  const refresh = async () => {
    setBusy(true);
    try {
      await action("refresh");
    } catch {
    } finally {
      setBusy(false);
    }
  };
  const selected = useMemo(
    () => new Set(snapshot?.settings.selected_runs || []),
    [snapshot?.settings.selected_runs],
  );
  const deferred = useDeferredValue(search.trim().toLocaleLowerCase());
  const grouped = useMemo(() => {
    if (!snapshot)
      return [] as {
        name: string;
        attempts: { name: string; sweeps: { name: string; runs: Run[] }[] }[];
      }[];
    const experiments = new Map<string, Map<string, Map<string, Run[]>>>();
    for (const run of snapshot.index.runs) {
      const hay = [
        run.experiment,
        run.attempt,
        run.sweep,
        run.run,
        JSON.stringify(run.params),
        JSON.stringify(run.shared),
      ]
        .join(" ")
        .toLocaleLowerCase();
      if (deferred && !hay.includes(deferred)) continue;
      if (!experiments.has(run.experiment))
        experiments.set(run.experiment, new Map());
      const attempts = experiments.get(run.experiment)!;
      if (!attempts.has(run.attempt)) attempts.set(run.attempt, new Map());
      const sweeps = attempts.get(run.attempt)!;
      if (!sweeps.has(run.sweep)) sweeps.set(run.sweep, []);
      sweeps.get(run.sweep)!.push(run);
    }
    return [...experiments]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, attempts]) => ({
        name,
        attempts: [...attempts]
          .sort((a, b) => {
            const latest = (sweeps: Map<string, Run[]>) => {
              let time = 0;
              for (const runs of sweeps.values())
                for (const run of runs)
                  time = Math.max(time, Date.parse(run.started) || 0);
              return time;
            };
            return latest(b[1]) - latest(a[1]) || b[0].localeCompare(a[0]);
          })
          .map(([attempt, sweeps]) => ({
            name: attempt,
            sweeps: [...sweeps]
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([sweep, runs]) => ({
                name: sweep,
                runs: runs.sort((a, b) => a.run.localeCompare(b.run)),
              })),
          })),
      }));
  }, [snapshot?.index.runs, deferred]);
  const counts = useMemo(() => {
    const runs = snapshot?.index.runs || [];
    return {
      runs: runs.length,
      attempts: new Set(runs.map((r) => `${r.experiment}/${r.attempt}`)).size,
      sweeps: new Set(runs.map((r) => parent(r.path))).size,
      experiments: new Set(runs.map((r) => r.experiment)).size,
    };
  }, [snapshot?.index.runs]);
  const membersBySweep = useMemo(() => {
    const result = new Map<string, Run[]>();
    for (const run of snapshot?.index.runs || []) {
      const path = parent(run.path);
      if (!result.has(path)) result.set(path, []);
      result.get(path)!.push(run);
    }
    return result;
  }, [snapshot?.index.runs]);
  const panelOpen = useCallback(
    (kind: PanelKind, path: string) =>
      snapshot?.settings.panels[kind]?.[path] ?? defaults[kind],
    [snapshot?.settings],
  );
  const togglePanel = (kind: PanelKind, path: string) => {
    action("panel", { kind, path, open: !panelOpen(kind, path) }).catch(
      () => {},
    );
  };
  const select = (
    kind: "attempt" | "sweep" | "run",
    path: string,
    checked: boolean,
  ) => {
    action("select", { kind, path, checked }).catch(() => {});
  };
  const plotOptions = (changes: Partial<Settings["plot"]>) => {
    if (!snapshot) return;
    action("plot_options", { ...snapshot.settings.plot, ...changes }).catch(
      () => {},
    );
  };
  const mutate = (
    kind: Kind,
    path: string,
    operation: "rename" | "delete",
    name?: string,
  ) => action(operation, { kind, path, name });
  if (!snapshot)
    return (
      <div className="coordinator-browser">
        <h2>Simulation results</h2>
        <p>{error || "Loading results…"}</p>
      </div>
    );
  const warnings = [snapshot.settings_error, ...snapshot.index.warnings].filter(
    Boolean,
  );
  const visible = grouped.reduce(
    (n, e) =>
      n +
      e.attempts.reduce(
        (m, a) => m + a.sweeps.reduce((q, s) => q + s.runs.length, 0),
        0,
      ),
    0,
  );
  return (
    <div className="coordinator-browser">
      <h2>Simulation results</h2>
      <div className="coordinator-plot-area">
        <div className="coordinator-plot-controls">
          <label>
            Metric:{" "}
            <select
              value={plot?.metric || ""}
              disabled={!plot?.metrics.length}
              onChange={(e) => plotOptions({ metric: e.target.value })}
            >
              {(plot?.metrics || []).map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={snapshot.settings.plot.logx}
              onChange={(e) => plotOptions({ logx: e.target.checked })}
            />{" "}
            Log X
          </label>
          <label>
            <input
              type="checkbox"
              checked={snapshot.settings.plot.logy}
              onChange={(e) => plotOptions({ logy: e.target.checked })}
            />{" "}
            Log Y
          </label>
        </div>
        <PlotView plot={plot} selected={selected.size} />
      </div>
      <div className="coordinator-toolbar">
        <input
          aria-label="Search results"
          placeholder="Search experiments, attempts, sweeps, runs, parameters"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button onClick={refresh} disabled={busy}>
          ⟳ Refresh
        </button>
        <button
          onClick={() => action("clear_selection").catch(() => {})}
          disabled={busy || selected.size === 0}
        >
          Clear plot
        </button>
      </div>
      <div className="coordinator-summary">
        <b>{plural(counts.runs, "run")}</b> ·{" "}
        {plural(counts.attempts, "attempt")} · {plural(counts.sweeps, "sweep")}{" "}
        · {plural(counts.experiments, "experiment")}
        {search.trim() ? ` · ${plural(visible, "matching run")}` : ""}
      </div>
      {error && (
        <p role="alert" className="coordinator-error">
          {error}
        </p>
      )}
      {warnings.length > 0 && (
        <div className="coordinator-warnings">
          {warnings.slice(0, 10).map((w, i) => (
            <div key={i}>{w}</div>
          ))}
          {warnings.length > 10 && (
            <div>…and {warnings.length - 10} more warnings</div>
          )}
        </div>
      )}
      <ResultsTree
        grouped={grouped}
        searching={Boolean(search.trim())}
        selected={selected}
        membersBySweep={membersBySweep}
        rpc={rpc}
        generation={generation}
        panelOpen={panelOpen}
        togglePanel={togglePanel}
        select={select}
        mutate={mutate}
      />
    </div>
  );
}

export function render({ model, el }: { model: Model; el: HTMLElement }) {
  const root = createRoot(el);
  root.render(<App model={model} />);
  return () => root.unmount();
}
