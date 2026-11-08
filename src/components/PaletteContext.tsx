import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { PaletteCtx } from "../paletteContext";

/** Holds whether the palette is open and listens for Cmd+K / Ctrl+K anywhere on the page. */
export function PaletteProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  const value = useMemo(() => ({ open, setOpen }), [open]);
  return <PaletteCtx.Provider value={value}>{children}</PaletteCtx.Provider>;
}
