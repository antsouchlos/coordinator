export type Kind = "experiment" | "attempt" | "sweep" | "run";
export type PanelKind = Kind | "patch" | "data" | "metadata";
export type Run = {
  path: string;
  experiment: string;
  attempt: string;
  sweep: string;
  run: string;
  started: string;
  axis: string;
  params: Record<string, unknown>;
  shared: Record<string, unknown>;
  has_patch: boolean;
};
export type Settings = {
  version: number;
  plot: { metric: string | null; logx: boolean; logy: boolean };
  selected_runs: string[];
  panels: Record<PanelKind, Record<string, boolean>>;
};
export type Snapshot = {
  generation: number;
  index: { runs: Run[]; warnings: string[] };
  settings: Settings;
  settings_error: string;
};
export type Plot = {
  metrics: string[];
  metric?: string;
  figure: Record<string, unknown> | null;
  error: string | null;
};
export type Response = {
  id: number;
  ok: boolean;
  error?: string;
  snapshot?: Snapshot;
  settings?: Settings;
  settings_error?: string;
  plot?: Plot;
  content?: any;
};
export type Model = {
  send: (value: unknown) => void;
  on: (name: string, callback: (value: Response) => void) => void;
  off: (name: string, callback: (value: Response) => void) => void;
};
export type Rpc = (
  action: string,
  payload?: Record<string, unknown>,
) => Promise<Response>;
export type GroupedSweep = { name: string; runs: Run[] };
export type GroupedAttempt = { name: string; sweeps: GroupedSweep[] };
export type GroupedExperiment = { name: string; attempts: GroupedAttempt[] };

export const defaults: Record<PanelKind, boolean> = {
  experiment: true,
  attempt: true,
  sweep: true,
  run: false,
  patch: true,
  data: false,
  metadata: false,
};
export const labelParts = (name: string): [string, string] => {
  const i = name.lastIndexOf("@");
  return i < 0 ? ["", name] : [name.slice(0, i), name.slice(i + 1)];
};
export const plural = (n: number, word: string) =>
  `${n} ${word}${n === 1 ? "" : "s"}`;
export const valueText = (value: unknown) =>
  value == null
    ? ""
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
export const parent = (path: string) => path.slice(0, path.lastIndexOf("/"));
