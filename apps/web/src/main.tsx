import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((err: unknown) => {
      console.error("Service worker registration failed", err);
    });
  });
}

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("Root element #root missing");
}

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
