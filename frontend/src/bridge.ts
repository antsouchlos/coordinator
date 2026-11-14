import { useCallback, useEffect, useRef, useState } from "react";
import type { Model, PanelKind, Response, Rpc } from "./types";

export function useBridge(model: Model) {
  const pending = useRef(
    new Map<
      number,
      { resolve: (r: Response) => void; reject: (e: Error) => void }
    >(),
  );
  const next = useRef(0);
  useEffect(() => {
    const receive = (response: Response) => {
      const wait = pending.current.get(response.id);
      if (!wait) return;
      pending.current.delete(response.id);
      response.ok
        ? wait.resolve(response)
        : wait.reject(new Error(response.error || "Browser request failed."));
    };
    model.on("msg:custom", receive);
    return () => {
      model.off("msg:custom", receive);
      pending.current.forEach((wait) =>
        wait.reject(new Error("Browser closed.")),
      );
      pending.current.clear();
    };
  }, [model]);
  return useCallback<Rpc>(
    (action, payload = {}) =>
      new Promise((resolve, reject) => {
        const id = ++next.current;
        pending.current.set(id, { resolve, reject });
        model.send({ id, action, payload });
      }),
    [model],
  );
}

export function useContent(
  rpc: Rpc,
  generation: number,
  kind: PanelKind,
  path: string,
  enabled: boolean,
  page = 0,
) {
  const [state, setState] = useState<{
    loading: boolean;
    data: any;
    error: string | null;
  }>({ loading: false, data: null, error: null });
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    setState({ loading: true, data: null, error: null });
    rpc("content", { generation, kind, path, page })
      .then((r) => {
        if (live) setState({ loading: false, data: r.content, error: null });
      })
      .catch((e) => {
        if (live) setState({ loading: false, data: null, error: e.message });
      });
    return () => {
      live = false;
    };
  }, [rpc, generation, kind, path, enabled, page]);
  return state;
}
