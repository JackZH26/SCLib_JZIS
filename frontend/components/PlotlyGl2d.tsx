"use client";

/**
 * Plotly component backed by the GL2D distribution rather than the full
 * 40+ trace bundle. The timeline only renders scattergl, so loading maps,
 * 3D scenes, finance charts, and the SVG-only trace families is unnecessary.
 */
import Plotly from "plotly.js/dist/plotly-gl2d.min.js";
import createPlotlyComponent from "react-plotly.js/factory";

export default createPlotlyComponent(Plotly);
