/** The colours the charts draw with.
 *
 *  One source for every chart in the application, because two palettes drifting
 *  apart is how a product ends up with an orange "Cash" on one page and a green
 *  one on the next.
 *
 *  **Dark is a separate palette, not a filter over the light one.** Lightening or
 *  darkening a light-mode hue by a fixed amount breaks the two things that make a
 *  categorical palette work: every slot has to stay inside a narrow lightness
 *  band so none of them shouts, and adjacent slots have to stay apart for a
 *  colourblind reader. Both sets below were run through the dataviz validator
 *  against the surface they are actually painted on:
 *
 *    light on #ffffff  — all checks pass, worst adjacent CVD ΔE 9.1, normal 19.6
 *    dark  on #191920  — all checks pass, worst adjacent CVD ΔE 8.4, normal 19.3
 *
 *  Three light slots sit under 3:1 against white. The method allows that only
 *  with relief, and the relief is real here: every chart has a hover readout and
 *  a table view of the same figures. The dark set clears 3:1 outright.
 *
 *  Slots are assigned in order and never cycled. A seventh series folds into
 *  "Other" rather than reusing slot one, so no two lines on a chart share a hue.
 */
import { useTheme } from "./hooks/useTheme";
import { resolved } from "./theme";

const LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];
const DARK  = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"];

export interface ChartPalette {
  /** Categorical slots, in fixed assignment order. */
  slots: string[];
  /** A single series takes slot one, with no legend. */
  one: string;
  /** Gridlines: present enough to read a value against, quiet enough to ignore. */
  grid: string;
  /** The axis rule, a step stronger than the grid. */
  axis: string;
  dark: boolean;
}

function build(dark: boolean): ChartPalette {
  const slots = dark ? DARK : LIGHT;
  return {
    slots,
    one: slots[0],
    // White at low alpha on dark, ink at low alpha on light. Alpha rather than a
    // solid colour so a gridline over a filled area stays a gridline.
    grid: dark ? "rgba(255,255,255,0.10)" : "rgba(20,20,26,0.10)",
    axis: dark ? "rgba(255,255,255,0.22)" : "rgba(20,20,26,0.20)",
    dark,
  };
}

/** For charts inside React, which must repaint when the theme moves. */
export function useChartPalette(): ChartPalette {
  const { mode } = useTheme();
  return build(mode === "dark");
}

/** For the few places that need a colour outside a component. */
export function chartPalette(): ChartPalette {
  return build(resolved() === "dark");
}
