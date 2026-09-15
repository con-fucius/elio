import { useEffect, useState } from "react";
import { getMeta, LAST_SYNC_KEY } from "../lib/localStore";

export function useLastSync(): string | null {
  const [value, setValue] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMeta(LAST_SYNC_KEY)
      .then((v) => {
        if (!cancelled) setValue(v);
      })
      .catch(() => {
        if (!cancelled) setValue(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return value;
}
