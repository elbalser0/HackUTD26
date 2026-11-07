import { useCallback, useEffect, useState } from "react";

export type Async<T> =
  | { state: "loading" }
  | { state: "error"; error: unknown }
  | { state: "ok"; data: T };

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [s, setS] = useState<Async<T>>({ state: "loading" });
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    fn().then(
      (data) => live && setS({ state: "ok", data }),
      (error) => live && setS({ state: "error", error }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line
  }, [...deps, n]);
  const reload = useCallback(() => {
    setS({ state: "loading" });
    setN((x) => x + 1);
  }, []);
  const set = useCallback((data: T) => setS({ state: "ok", data }), []);
  return { s, reload, set };
}
