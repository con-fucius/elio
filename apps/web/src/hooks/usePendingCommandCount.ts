import { useCallback, useEffect, useState } from "react";
import { countNonTerminalCommands } from "../lib/localStore";

export function usePendingCommandCount(): {
  count: number;
  error: string | null;
  refresh: () => void;
} {
  const [count, setCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    countNonTerminalCommands()
      .then((n) => {
        if (!cancelled) {
          setCount(n);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to read local command queue");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  return { count, error, refresh };
}
