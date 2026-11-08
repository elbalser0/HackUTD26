import { createContext, useContext } from "react";

export interface PaletteState {
  open: boolean;
  setOpen: (v: boolean | ((o: boolean) => boolean)) => void;
}
export const PaletteCtx = createContext<PaletteState>({
  open: false,
  setOpen: () => {},
});
export const usePalette = () => useContext(PaletteCtx);
