import { useCallback, useEffect, useRef, useState } from "react";
import { defaults, parent } from "./types";
import type { PanelKind, Response, Snapshot } from "./types";

type GroupKind = "experiment" | "attempt" | "sweep";
type PanelAction = (
  name: string,
  payload: Record<string, unknown>,
) => Promise<Response>;
type Pending = {
  id: number;
  kind: PanelKind;
  path: string;
  open: boolean;
  all: boolean;
  sent: boolean;
  cancelled: boolean;
  timer: number | null;
};

function applies(operation: Pending, kind: PanelKind, path: string) {
  if (operation.kind !== kind) return false;
  if (!operation.all) return operation.path === path;
  return kind === "experiment" || parent(operation.path) === parent(path);
}

function currentState(
  snapshot: Snapshot | null,
  operations: Pending[],
  kind: PanelKind,
  path: string,
) {
  let open = snapshot?.settings.panels[kind]?.[path] ?? defaults[kind];
  for (const operation of operations)
    if (applies(operation, kind, path)) open = operation.open;
  return open;
}

export function usePanelToggles(
  snapshot: Snapshot | null,
  action: PanelAction,
) {
  const [operations, setOperations] = useState<Pending[]>([]);
  const pending = useRef<Pending[]>([]);
  const nextId = useRef(0);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const actionRef = useRef(action);
  actionRef.current = action;

  const update = useCallback((change: (items: Pending[]) => Pending[]) => {
    pending.current = change(pending.current);
    setOperations(pending.current);
  }, []);
  const remove = useCallback(
    (id: number) => update((items) => items.filter((item) => item.id !== id)),
    [update],
  );
  const send = useCallback(
    (operation: Pending) => {
      operation.timer = null;
      queue.current = queue.current.then(async () => {
        if (operation.cancelled) return;
        operation.sent = true;
        try {
          await actionRef.current(operation.all ? "panel_all" : "panel", {
            kind: operation.kind,
            path: operation.path,
            open: operation.open,
          });
        } catch {
          // The shared action handler reports the error.
        } finally {
          remove(operation.id);
        }
      });
    },
    [remove],
  );

  const panelOpen = useCallback(
    (kind: PanelKind, path: string) =>
      currentState(snapshot, operations, kind, path),
    [snapshot?.settings, operations],
  );
  const togglePanel = (kind: PanelKind, path: string) => {
    const operation: Pending = {
      id: ++nextId.current,
      kind,
      path,
      open: !currentState(snapshot, pending.current, kind, path),
      all: false,
      sent: false,
      cancelled: false,
      timer: null,
    };
    update((items) => [...items, operation]);
    operation.timer = window.setTimeout(() => send(operation), 450);
  };
  const toggleAllPanels = (kind: GroupKind, path: string, open: boolean) => {
    for (const operation of pending.current) {
      if (
        operation.kind !== kind ||
        operation.path !== path ||
        operation.all ||
        operation.sent
      )
        continue;
      if (operation.timer !== null) window.clearTimeout(operation.timer);
      operation.timer = null;
      operation.cancelled = true;
    }
    update((items) => items.filter((item) => !item.cancelled));
    const operation: Pending = {
      id: ++nextId.current,
      kind,
      path,
      open,
      all: true,
      sent: false,
      cancelled: false,
      timer: null,
    };
    update((items) => [...items, operation]);
    send(operation);
  };

  useEffect(
    () => () => {
      for (const operation of pending.current) {
        if (operation.timer === null || operation.cancelled) continue;
        window.clearTimeout(operation.timer);
        send(operation);
      }
    },
    [send],
  );

  return { panelOpen, togglePanel, toggleAllPanels };
}
