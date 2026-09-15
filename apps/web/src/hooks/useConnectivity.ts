import { useEffect, useState } from "react";

export interface ConnectivityState {
  online: boolean;
  /** Effective online = navigator.onLine; APIs can still be down — callers must not equate this with server health. */
  navigatorOnline: boolean;
}

export function useConnectivity(): ConnectivityState {
  const [navigatorOnline, setNavigatorOnline] = useState(() =>
    typeof navigator === "undefined" ? true : navigator.onLine,
  );

  useEffect(() => {
    const goOnline = () => setNavigatorOnline(true);
    const goOffline = () => setNavigatorOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  return { online: navigatorOnline, navigatorOnline };
}
