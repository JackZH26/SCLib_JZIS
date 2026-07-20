"use client";

/**
 * SVG-only Plotly bundle used when WebGL is unavailable. Keeping this in a
 * separate dynamic chunk means normal browsers continue to download only the
 * smaller GL2D bundle, while locked-down/older browsers still get a chart.
 */
import Plotly from "plotly.js/dist/plotly-basic.min.js";
import createPlotlyComponent from "react-plotly.js/factory";

export default createPlotlyComponent(Plotly);
