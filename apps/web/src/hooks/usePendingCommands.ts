import { useCallback, useEffect, useState } from "react";
import { listPendingCommands, type PendingCommand } from "../lib/localStore";

export function usePendingCommands(): {
  commands: PendingCommand[];
  error: string | null;
  refresh: () => void;
} {
  const [commands, setCommands] = useState<PendingCommand[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    listPendingCommands()
      .then((rows) => {
        if (!cancelled) {
          setCommands(rows);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to read command queue");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  return { commands, error, refresh };
}
