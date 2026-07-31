import { useLayoutEffect } from "react";

import logoUrl from "../loraforge-logo.png";
import PipelineShell from "./components/PipelineShell";
import "@xyflow/react/dist/style.css";
import "../styles.css";
import "../canvas.css";

export default function App() {
  useLayoutEffect(() => {
    let cancelled = false;
    const boot = async () => {
      window.LoRAForgeAssets = { logo: logoUrl };
      window.__loraforgeCanvasBootFallback = window.setTimeout(() => {
        document.documentElement.classList.remove("canvas-booting");
        document.getElementById("canvas-boot-screen")?.remove();
      }, 6000);
      await import("./i18n.js");
      if (cancelled) return;
      await import("./controller");
      if (cancelled) return;
      await import("./canvas");
    };
    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  return <PipelineShell />;
}

declare global {
  interface Window {
    __loraforgeCanvasBootFallback?: number;
    LoRAForgeAssets?: { logo: string };
  }
}
