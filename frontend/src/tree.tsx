import React, { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useContent } from "./bridge";
import { labelParts, valueText } from "./types";
import type { Kind, PanelKind, Response, Rpc, Run } from "./types";

export function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={`coordinator-chevron ${open ? "" : "closed"}`}
      aria-hidden="true"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m4 7 6 6 6-6" />
    </svg>
  );
}

export function VirtualBlocks<T>({
  items,
  getKey,
  renderItem,
  estimate,
  maxHeight,
}: {
  items: T[];
  getKey: (item: T) => string;
  renderItem: (item: T) => React.ReactNode;
  estimate: number;
  maxHeight: number;
}) {
  const scroll = useRef<HTMLDivElement>(null);
  const virtual = useVirtualizer({
    count: items.length,
    getScrollElement: () => scroll.current,
    estimateSize: () => estimate,
    overscan: 2,
  });
  if (items.length <= 12)
    return (
      <>
        {items.map((item) => (
          <React.Fragment key={getKey(item)}>{renderItem(item)}</React.Fragment>
        ))}
      </>
    );
  return (
    <div
      className="coordinator-block-scroll"
      ref={scroll}
      style={{ height: Math.min(maxHeight, virtual.getTotalSize()) }}
    >
      <div style={{ height: virtual.getTotalSize(), position: "relative" }}>
        {virtual.getVirtualItems().map((row) => (
          <div
            key={getKey(items[row.index])}
            data-index={row.index}
            ref={virtual.measureElement}
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: "100%",
              transform: `translateY(${row.start}px)`,
            }}
          >
            {renderItem(items[row.index])}
          </div>
        ))}
      </div>
    </div>
  );
}

export function EditableName({
  kind,
  path,
  name,
  mutate,
}: {
  kind: Kind;
  path: string;
  name: string;
  mutate: (
    kind: Kind,
    path: string,
    operation: "rename" | "delete",
    name?: string,
  ) => Promise<Response>;
}) {
  const [label, id] = kind === "experiment" ? [name, ""] : labelParts(name);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(label);
  const [error, setError] = useState("");
  const pending = useRef(false);
  useEffect(() => {
    setDraft(label);
    setEditing(false);
    setError("");
  }, [path, label]);
  const submit = async () => {
    if (pending.current) return;
    if (draft === label) {
      setEditing(false);
      return;
    }
    pending.current = true;
    try {
      await mutate(kind, path, "rename", draft);
      setEditing(false);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      pending.current = false;
    }
  };
  const remove = async () => {
    if (
      !window.confirm(
        `Permanently delete ${kind} “${name}” and everything under ${path}?`,
      )
    )
      return;
    try {
      await mutate(kind, path, "delete");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <span className="coordinator-name-group">
      {editing ? (
        <input
          className="coordinator-name-input"
          aria-label={`${kind === "experiment" ? "Rename" : "Edit"} ${kind}${kind === "experiment" ? "" : " label"}`}
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
            if (e.key === "Escape") {
              setEditing(false);
              setError("");
            }
          }}
          onBlur={submit}
        />
      ) : (
        <button
          className="coordinator-editable"
          title="Edit label"
          onClick={() => setEditing(true)}
        >
          {label || "Add label"}
        </button>
      )}
      {id && (
        <span className="coordinator-id">
          {label ? "@" : " · "}
          {id}
        </span>
      )}
      <button
        className="coordinator-delete"
        title={`Delete ${kind}`}
        aria-label={`Delete ${kind} ${name}`}
        onClick={remove}
      >
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M4 7h16M10 4h4l1 3H9l1-3ZM6 7l1 13h10l1-13M10 11v6M14 11v6" />
        </svg>
      </button>
      {error && (
        <span className="coordinator-error coordinator-inline-error">
          {error}
        </span>
      )}
    </span>
  );
}

export function PatchPanel({
  path,
  open,
  toggle,
  rpc,
  generation,
}: {
  path: string;
  open: boolean;
  toggle: () => void;
  rpc: Rpc;
  generation: number;
}) {
  const state = useContent(rpc, generation, "patch", path, open);
  return (
    <div className={`coordinator-patch ${open ? "" : "closed"}`}>
      <button
        onClick={toggle}
        aria-label={open ? "Close source patch" : "Open source patch"}
        aria-expanded={open}
      >
        <b>Source patch</b>
        <Chevron open={open} />
      </button>
      {open && (
        <div className="coordinator-patch-content">
          {state.loading ? (
            "Loading…"
          ) : state.error ? (
            <span className="coordinator-error">{state.error}</span>
          ) : (
            <pre>{state.data?.text}</pre>
          )}
        </div>
      )}
    </div>
  );
}

export function RunTable({
  runs,
  allMembers,
  selected,
  select,
  mutate,
  rpc,
  generation,
  panelOpen,
  togglePanel,
  path,
}: {
  runs: Run[];
  allMembers: Run[];
  selected: Set<string>;
  select: (
    kind: "run" | "sweep" | "attempt",
    path: string,
    checked: boolean,
  ) => void;
  mutate: (
    kind: Kind,
    path: string,
    operation: "rename" | "delete",
    name?: string,
  ) => Promise<Response>;
  rpc: Rpc;
  generation: number;
  panelOpen: (kind: PanelKind, path: string) => boolean;
  togglePanel: (kind: PanelKind, path: string) => void;
  path: string;
}) {
  const params = useMemo(
    () => [...new Set(runs.flatMap((r) => Object.keys(r.params)))].sort(),
    [runs],
  );
  const shared = useMemo(
    () => [...new Set(runs.flatMap((r) => Object.keys(r.shared)))].sort(),
    [runs],
  );
  const scroll = useRef<HTMLDivElement>(null);
  const virtual = useVirtualizer({
    count: runs.length,
    getScrollElement: () => scroll.current,
    estimateSize: () => 74,
    overscan: 6,
  });
  const every = allMembers.every((r) => selected.has(r.path));
  const some = allMembers.some((r) => selected.has(r.path));
  const checkbox = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (checkbox.current) checkbox.current.indeterminate = some && !every;
  }, [some, every]);
  const valueWidths = useMemo(
    () =>
      [
        ...params.map((name) => ({ name, field: "params" as const })),
        ...shared.map((name) => ({ name, field: "shared" as const })),
      ].map(({ name, field }) => {
        let longest = name.length;
        for (const run of runs) {
          longest = Math.max(longest, valueText(run[field][name]).length);
          if (longest >= 21) break;
        }
        return Math.min(180, Math.max(80, longest * 8 + 16));
      }),
    [runs, params, shared],
  );
  const columnWidths = [220, ...valueWidths, 90, 184];
  const columns = columnWidths.map((width) => `${width}px`).join(" ");
  return (
    <div className="coordinator-table-outer">
      <div
        className="coordinator-table"
        style={{ width: columnWidths.reduce((sum, width) => sum + width, 16) }}
      >
        <div
          className="coordinator-table-head"
          style={{ gridTemplateColumns: columns }}
        >
          <div>
            <label>
              <input
                ref={checkbox}
                type="checkbox"
                checked={every}
                onChange={(e) => select("sweep", path, e.target.checked)}
              />{" "}
              Run
            </label>
          </div>
          {params.map((p) => (
            <div key={`p${p}`} title={p}>
              {p}
            </div>
          ))}
          {shared.map((p) => (
            <div key={`s${p}`} title={p}>
              {p}
            </div>
          ))}
          <div>Axis</div>
          <div>Started</div>
        </div>
        <div
          className="coordinator-run-scroll"
          ref={scroll}
          style={{
            height: Math.min(550, Math.max(80, virtual.getTotalSize())),
          }}
        >
          <div style={{ height: virtual.getTotalSize(), position: "relative" }}>
            {virtual.getVirtualItems().map((v) => {
              const run = runs[v.index];
              return (
                <div
                  key={run.path}
                  data-index={v.index}
                  ref={virtual.measureElement}
                  className={`coordinator-virtual-row${v.index === runs.length - 1 ? " coordinator-final-row" : ""}`}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${v.start}px)`,
                  }}
                >
                  <RunRow
                    run={run}
                    params={params}
                    shared={shared}
                    columns={columns}
                    selected={selected.has(run.path)}
                    select={select}
                    mutate={mutate}
                    rpc={rpc}
                    generation={generation}
                    panelOpen={panelOpen}
                    togglePanel={togglePanel}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function RunRow({
  run,
  params,
  shared,
  columns,
  selected,
  select,
  mutate,
  rpc,
  generation,
  panelOpen,
  togglePanel,
}: {
  run: Run;
  params: string[];
  shared: string[];
  columns: string;
  selected: boolean;
  select: (kind: "run", path: string, checked: boolean) => void;
  mutate: (
    kind: Kind,
    path: string,
    operation: "rename" | "delete",
    name?: string,
  ) => Promise<Response>;
  rpc: Rpc;
  generation: number;
  panelOpen: (kind: PanelKind, path: string) => boolean;
  togglePanel: (kind: PanelKind, path: string) => void;
}) {
  const dataOpen = panelOpen("data", run.path),
    metaOpen = panelOpen("metadata", run.path);
  const [page, setPage] = useState(0);
  const data = useContent(rpc, generation, "data", run.path, dataOpen, page);
  const metadata = useContent(rpc, generation, "metadata", run.path, metaOpen);
  return (
    <>
      <div
        className="coordinator-table-row"
        style={{ gridTemplateColumns: columns }}
      >
        <div className="coordinator-run-name">
          <label>
            <input
              type="checkbox"
              checked={selected}
              onChange={(e) => select("run", run.path, e.target.checked)}
            />
            <b>
              <EditableName
                kind="run"
                path={run.path}
                name={run.run}
                mutate={mutate}
              />
            </b>
          </label>
          <div className="coordinator-run-actions">
            <button onClick={() => togglePanel("data", run.path)}>
              View data
            </button>
            <button onClick={() => togglePanel("metadata", run.path)}>
              View metadata
            </button>
          </div>
        </div>
        {params.map((p) => (
          <div
            key={`p${p}`}
            title={p in run.params ? valueText(run.params[p]) : "—"}
          >
            {p in run.params ? valueText(run.params[p]) : "—"}
          </div>
        ))}
        {shared.map((p) => (
          <div
            key={`s${p}`}
            title={p in run.shared ? valueText(run.shared[p]) : "—"}
          >
            {p in run.shared ? valueText(run.shared[p]) : "—"}
          </div>
        ))}
        <div>{run.axis}</div>
        <div>{run.started}</div>
      </div>
      {dataOpen && (
        <div className="coordinator-detail">
          {data.loading ? (
            "Loading data…"
          ) : data.error ? (
            <span className="coordinator-error">{data.error}</span>
          ) : (
            data.data && (
              <>
                <div className="coordinator-data-scroll">
                  <table>
                    <thead>
                      <tr>
                        {data.data.columns.map((c: string) => (
                          <th key={c}>{c}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.data.rows.map((row: unknown[], i: number) => (
                        <tr key={i}>
                          {row.map((cell, j) => (
                            <td key={j}>{valueText(cell)}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {data.data.pages > 1 && (
                  <div className="coordinator-pager">
                    <button
                      disabled={page === 0}
                      onClick={() => setPage((p) => p - 1)}
                    >
                      Previous
                    </button>
                    <span>
                      Page {page + 1} of {data.data.pages}
                    </span>
                    <button
                      disabled={page + 1 >= data.data.pages}
                      onClick={() => setPage((p) => p + 1)}
                    >
                      Next
                    </button>
                  </div>
                )}
              </>
            )
          )}
        </div>
      )}
      {metaOpen && (
        <div className="coordinator-detail">
          <code>{metadata.data?.path}</code>
          {metadata.loading ? (
            "Loading metadata…"
          ) : metadata.error ? (
            <span className="coordinator-error">{metadata.error}</span>
          ) : (
            <pre>{metadata.data?.text}</pre>
          )}
        </div>
      )}
    </>
  );
}
