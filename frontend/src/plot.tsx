import React, { useEffect, useRef, useState } from "react";
import Plotly from "plotly.js-basic-dist-min";
import type { Plot } from "./types";

const emptyLayout = {
  autosize: true,
  height: 600,
  template: "plotly_white",
  margin: { b: 120 },
  xaxis: { title: "Axis", showline: true },
  yaxis: { title: "Metric", showline: true },
};

const annotationEntities: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};
const escapeAnnotation = (value: string) =>
  value.replace(/[&<>"']/g, (character) => annotationEntities[character]);

const record = (value: unknown): Record<string, any> =>
  value && typeof value === "object" ? (value as Record<string, any>) : {};

function themedLayout(element: HTMLElement, original: Record<string, unknown>) {
  const style = getComputedStyle(element);
  const color = (name: string, fallback: string) =>
    style.getPropertyValue(name).trim() || fallback;
  const background = color("--surface", "#fff");
  const raised = color("--raised", "#f7f9fb");
  const text = color("--text", "#213143");
  const grid = color("--subtle-line", "#e3e8ed");
  const line = color("--line", "#d6dfe8");
  const template = record(original.template);
  const templateLayout = record(template.layout);
  const axis = (value: unknown) => ({
    ...record(value),
    gridcolor: grid,
    linecolor: line,
    zerolinecolor: grid,
  });
  return {
    ...original,
    template: {
      ...template,
      layout: {
        ...templateLayout,
        paper_bgcolor: background,
        plot_bgcolor: background,
        font: { ...record(templateLayout.font), color: text },
        xaxis: axis(templateLayout.xaxis),
        yaxis: axis(templateLayout.yaxis),
      },
    },
    paper_bgcolor: background,
    plot_bgcolor: background,
    font: { ...record(original.font), color: text },
    xaxis: axis(original.xaxis),
    yaxis: axis(original.yaxis),
    hoverlabel: {
      ...record(original.hoverlabel),
      bgcolor: raised,
      font: { ...record(record(original.hoverlabel).font), color: text },
    },
  };
}

export function PlotView({
  plot,
  selected,
}: {
  plot: Plot | null;
  selected: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const lastLayout = useRef<Record<string, unknown>>(emptyLayout);
  const [themeVersion, setThemeVersion] = useState(0);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const figure = plot?.figure as
      | { data: any[]; layout: Record<string, unknown> }
      | undefined;
    if (figure) lastLayout.current = figure.layout;
    const message =
      plot?.error || (selected === 0 ? "Select runs to plot" : null);
    const baseLayout = figure?.layout || {
      ...lastLayout.current,
      annotations: message
        ? [
            {
              text: escapeAnnotation(message),
              x: 0.5,
              y: 0.5,
              xref: "paper",
              yref: "paper",
              showarrow: false,
              font: {
                color: plot?.error
                  ? getComputedStyle(element)
                      .getPropertyValue("--error")
                      .trim() || "#a22"
                  : getComputedStyle(element)
                      .getPropertyValue("--muted")
                      .trim() || "#666",
              },
            },
          ]
        : [],
    };
    Plotly.react(
      element,
      figure?.data || [],
      themedLayout(element, baseLayout),
      {
        responsive: true,
        displaylogo: false,
      },
    );
  }, [plot?.figure, plot?.error, selected, themeVersion]);

  useEffect(() => {
    const observer = new MutationObserver(() =>
      setThemeVersion((value) => value + 1),
    );
    observer.observe(document.documentElement, { attributes: true });
    if (document.body) observer.observe(document.body, { attributes: true });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(() => {
      if (element.classList.contains("js-plotly-plot"))
        Plotly.Plots.resize(element);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      Plotly.purge(element);
    };
  }, []);
  return <div className="coordinator-plot" ref={ref} />;
}
