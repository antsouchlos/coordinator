import React, { useEffect, useRef } from "react";
import {
  Chevron,
  EditableName,
  PatchPanel,
  RunTable,
  VirtualBlocks,
} from "./tree";
import { plural } from "./types";
import type {
  GroupedAttempt,
  GroupedExperiment,
  GroupedSweep,
  Kind,
  PanelKind,
  Response,
  Rpc,
  Run,
} from "./types";

type TreeProps = {
  grouped: GroupedExperiment[];
  searching: boolean;
  selected: Set<string>;
  membersBySweep: Map<string, Run[]>;
  rpc: Rpc;
  generation: number;
  panelOpen: (kind: PanelKind, path: string) => boolean;
  togglePanel: (kind: PanelKind, path: string) => void;
  toggleAllPanels: (kind: GroupKind, path: string, open: boolean) => void;
  previewPatchWidth: (width: number) => void;
  commitPatchWidth: (width: number) => void;
  resetPatchWidth: () => void;
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
};
type SharedProps = Omit<TreeProps, "grouped" | "searching">;
type GroupKind = "experiment" | "attempt" | "sweep";

function isHeadingToggleTarget(target: EventTarget) {
  if (!(target instanceof Element)) return true;
  const control = target.closest("button, input, a, select, textarea");
  return (
    !control ||
    control.matches(".coordinator-disclosure, .coordinator-chevron-button")
  );
}

function Heading({
  kind,
  path,
  name,
  extra,
  panelOpen,
  togglePanel,
  toggleAllPanels,
  mutate,
}: Pick<
  TreeProps,
  "panelOpen" | "togglePanel" | "toggleAllPanels" | "mutate"
> & {
  kind: GroupKind;
  path: string;
  name: string;
  extra: React.ReactNode;
}) {
  const open = panelOpen(kind, path);
  const clickTimer = useRef<number | null>(null);
  const firstClickOpen = useRef<boolean | null>(null);
  useEffect(
    () => () => {
      if (clickTimer.current !== null) window.clearTimeout(clickTimer.current);
    },
    [],
  );
  return (
    <div
      className="coordinator-heading"
      onClick={(event) => {
        if (!isHeadingToggleTarget(event.target)) return;
        if (clickTimer.current !== null) {
          window.clearTimeout(clickTimer.current);
          clickTimer.current = null;
        }
        if (event.detail > 1) return;
        if (event.detail === 0) {
          firstClickOpen.current = null;
          togglePanel(kind, path);
          return;
        }
        firstClickOpen.current = open;
        clickTimer.current = window.setTimeout(() => {
          clickTimer.current = null;
          togglePanel(kind, path);
        }, 300);
      }}
      onDoubleClick={(event) => {
        if (!isHeadingToggleTarget(event.target)) return;
        event.preventDefault();
        if (clickTimer.current !== null) {
          window.clearTimeout(clickTimer.current);
          clickTimer.current = null;
        }
        toggleAllPanels(kind, path, !(firstClickOpen.current ?? open));
        firstClickOpen.current = null;
      }}
    >
      <button className="coordinator-disclosure" aria-expanded={open}>
        <span className="coordinator-prefix">
          {kind[0].toUpperCase() + kind.slice(1)}:{" "}
        </span>
      </button>
      <EditableName kind={kind} path={path} name={name} mutate={mutate} />
      <small>{extra}</small>
      <button
        className="coordinator-chevron-button"
        aria-label={`Toggle ${kind}`}
        aria-expanded={open}
      >
        <Chevron open={open} />
      </button>
    </div>
  );
}

function SweepCard({
  sweep,
  attemptPath,
  ...props
}: SharedProps & { sweep: GroupedSweep; attemptPath: string }) {
  const path = `${attemptPath}/${sweep.name}`;
  return (
    <section className="coordinator-card coordinator-sweep">
      <Heading
        kind="sweep"
        path={path}
        name={sweep.name}
        extra={plural(sweep.runs.length, "run")}
        {...props}
      />
      {props.panelOpen("sweep", path) && (
        <RunTable
          runs={sweep.runs}
          allMembers={props.membersBySweep.get(path) || []}
          selected={props.selected}
          select={props.select}
          mutate={props.mutate}
          rpc={props.rpc}
          generation={props.generation}
          panelOpen={props.panelOpen}
          togglePanel={props.togglePanel}
          path={path}
        />
      )}
    </section>
  );
}

function AttemptCard({
  attempt,
  experimentPath,
  ...props
}: SharedProps & { attempt: GroupedAttempt; experimentPath: string }) {
  const path = `${experimentPath}/${attempt.name}`;
  const runs = attempt.sweeps.flatMap((sweep) => sweep.runs);
  const dates = runs
    .map((run) => run.started)
    .filter(Boolean)
    .sort();
  const dateText =
    dates.length === 0
      ? "Unknown"
      : dates.length === 1
        ? dates[0]
        : `${dates[0]} – ${dates[dates.length - 1]}`;
  const patchOpen = props.panelOpen("patch", path);
  return (
    <section className="coordinator-card coordinator-attempt">
      <Heading
        kind="attempt"
        path={path}
        name={attempt.name}
        extra={`${plural(runs.length, "run")} · ${dateText}`}
        {...props}
      />
      {props.panelOpen("attempt", path) && (
        <div
          className={`coordinator-attempt-body${patchOpen ? "" : " coordinator-attempt-body-patch-closed"}`}
        >
          <div>
            <VirtualBlocks
              items={attempt.sweeps}
              getKey={(sweep) => sweep.name}
              estimate={180}
              maxHeight={760}
              renderItem={(sweep) => (
                <SweepCard sweep={sweep} attemptPath={path} {...props} />
              )}
            />
          </div>
          <PatchPanel
            path={path}
            open={patchOpen}
            toggle={() => props.togglePanel("patch", path)}
            rpc={props.rpc}
            generation={props.generation}
            previewWidth={props.previewPatchWidth}
            commitWidth={props.commitPatchWidth}
            resetWidth={props.resetPatchWidth}
          />
        </div>
      )}
    </section>
  );
}

function ExperimentCard({
  experiment,
  ...props
}: SharedProps & { experiment: GroupedExperiment }) {
  const path = experiment.name;
  const count = experiment.attempts.reduce(
    (total, attempt) =>
      total + attempt.sweeps.reduce((n, sweep) => n + sweep.runs.length, 0),
    0,
  );
  return (
    <section className="coordinator-card coordinator-experiment">
      <Heading
        kind="experiment"
        path={path}
        name={path}
        extra={`${plural(experiment.attempts.length, "attempt")} · ${plural(count, "run")}`}
        {...props}
      />
      {props.panelOpen("experiment", path) && (
        <div className="coordinator-card-body">
          <VirtualBlocks
            items={experiment.attempts}
            getKey={(attempt) => attempt.name}
            estimate={420}
            maxHeight={850}
            renderItem={(attempt) => (
              <AttemptCard attempt={attempt} experimentPath={path} {...props} />
            )}
          />
        </div>
      )}
    </section>
  );
}

export function ResultsTree({ grouped, searching, ...props }: TreeProps) {
  if (grouped.length === 0)
    return <p>{searching ? "No matching runs." : "No runs found."}</p>;
  return (
    <VirtualBlocks
      items={grouped}
      getKey={(experiment) => experiment.name}
      estimate={600}
      maxHeight={900}
      renderItem={(experiment) => (
        <ExperimentCard experiment={experiment} {...props} />
      )}
    />
  );
}
