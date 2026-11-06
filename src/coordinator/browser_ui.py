"""Jupyter widget overview for coordinator results."""

import html
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from coordinator.browser import delete_result, rename_result, scan_results
from coordinator.results import get_results_root


def _escape(value):
    return html.escape(str(value))


def _plural(word, count):
    return word if count == 1 else f"{word}s"


def _panel_chevron():
    return (
        "<svg class='coordinator-panel-chevron' aria-hidden='true' "
        "width='16' height='16' viewBox='0 0 16 16' "
        "style='flex:none;display:block;transform-box:view-box;transform-origin:8px 8px'>"
        "<path d='m3 5.5 5 5 5-5' fill='none' stroke='currentColor' "
        "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/></svg>"
    )


def _data_table(run):
    """Render every row and column of a run's CSV as escaped HTML."""
    try:
        frame = pd.read_csv(run.path / "data.csv")
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        return f"<span style='color:#a22'>Could not read data.csv: {_escape(exc)}</span>"
    return frame.to_html(index=False, escape=True, border=0, na_rep="")


def _runs_table(group, controls):
    """Render one wide run table with a visible horizontal scrollbar."""
    params = sorted({key for run in group for key in run.params})
    shared = sorted({key for run in group for key in run.shared})
    header_style = "text-align:left;padding:5px 7px;border-bottom:2px solid #c8d1db;white-space:nowrap"
    cell_style = "padding:5px 7px;border-bottom:1px solid #e3e8ed;white-space:nowrap"
    headers = ["Run", *params, *(f"Shared: {key}" for key in shared), "Axis", "Started"]
    rows = [
        "<tr>" + "".join(f"<th style='{header_style}'>{_escape(label)}</th>" for label in headers) + "</tr>"
    ]
    for run in group:
        metadata = json.dumps(run.metadata, indent=2, sort_keys=True, default=str)
        values = [
            f"<b>{controls('run', run.path, run.label)}</b>"
            "<div style='display:flex;gap:12px;margin-top:3px'>"
            "<details class='coordinator-view-data'>"
            "<summary style='cursor:pointer;color:#38638a'>View data</summary></details>"
            "<details class='coordinator-view-metadata'>"
            "<summary style='cursor:pointer;color:#38638a'>View metadata</summary></details>"
            "</div>",
            *(_escape(run.params[key]) if key in run.params else "—" for key in params),
            *(_escape(run.shared[key]) if key in run.shared else "—" for key in shared),
            _escape(run.axis),
            _escape(run.started),
        ]
        rows.append(
            "<tr class='coordinator-run'>"
            + "".join(f"<td style='{cell_style}'>{value}</td>" for value in values)
            + "</tr>"
        )
        rows.append(
            "<tr class='coordinator-run-data'><td "
            f"colspan='{len(headers)}' style='max-width:0;padding:8px 7px;"
            "border-bottom:1px solid #e3e8ed'>"
            "<div style='max-width:100%;overflow-x:auto'>"
            f"{_data_table(run)}</div></td></tr>"
        )
        rows.append(
            "<tr class='coordinator-run-metadata'><td "
            f"colspan='{len(headers)}' style='max-width:0;padding:8px 7px;"
            "border-bottom:1px solid #e3e8ed'>"
            f"<code style='display:block;white-space:normal;overflow-wrap:anywhere'>"
            f"{_escape(run.path)}</code>"
            "<pre style='white-space:pre-wrap;overflow-wrap:anywhere'>"
            f"{_escape(metadata)}</pre></td></tr>"
        )
    return (
        "<div style='box-sizing:border-box;width:100%;max-width:100%;"
        "overflow-x:scroll;overflow-y:hidden;scrollbar-gutter:stable;"
        "padding-bottom:12px'>"
        "<table style='border-collapse:collapse;font-size:12px;width:max-content;min-width:100%'>"
        + "".join(rows)
        + "</table></div>"
    )


def _group_runs(runs, term=""):
    """Group matching runs by experiment and revision directory."""
    term = term.casefold().strip()
    experiments = defaultdict(lambda: defaultdict(list))
    for run in runs:
        attempt = run.path.parent.name
        content = json.dumps(
            {"label": run.label, "params": run.params, "shared": run.shared},
            default=str,
        ).casefold()
        if term and not any(term in value for value in (
            run.experiment.casefold(), attempt.casefold(), content
        )):
            continue
        experiments[run.experiment][attempt].append(run)
    return [
        (
            experiment,
            [
                (attempt, sorted(group, key=lambda run: (run.label.casefold(), run.identity)))
                for attempt, group in sorted(
                    attempts.items(),
                    key=lambda item: (max(run.started for run in item[1]), item[0]),
                    reverse=True,
                )
            ],
        )
        for experiment, attempts in sorted(experiments.items())
    ]


def launch_results_browser(results_root: Path | str | None = None):
    """Return an expanded experiment/attempt/run overview for JupyterLab."""
    try:
        import ipywidgets as widgets
    except ImportError as exc:
        raise ImportError(
            "Install ipywidgets in this notebook's kernel (for example, pip install ipywidgets)."
        ) from exc
    try:
        from coordinator.browser_widget import ResultsOverview
    except ImportError as exc:
        raise ImportError(
            "Install anywidget in this notebook's kernel (for example, pip install anywidget)."
        ) from exc

    root = Path(results_root).expanduser().resolve() if results_root else get_results_root().resolve()
    runs = []
    targets = {}
    title = widgets.HTML("<h2 style='margin:0'>Simulation results</h2>")
    summary = widgets.HTML()
    search = widgets.Text(placeholder="Search experiments, revisions, runs, parameters")
    search.layout = widgets.Layout(width="min(560px, 75%)")
    refresh = widgets.Button(description="Refresh", icon="refresh")
    warnings = widgets.HTML()
    cards = ResultsOverview()
    cards.layout = widgets.Layout(width="100%", min_width="0px")

    def controls(kind, path, name, *, suffix="", placeholder=None, delete_name=None):
        key = str(len(targets))
        targets[key] = (kind, path)
        shown = name if name else placeholder or "Add name"
        delete_name = shown if delete_name is None else delete_name
        return (
            f"<span class='coordinator-editable' tabindex='0' role='button' "
            f"aria-label='Rename {kind}' data-result-id='{key}' "
            f"data-kind='{kind}' data-edit-name='{_escape(name)}'>"
            f"{_escape(shown)}</span>"
            f"{suffix}"
            f"<button class='coordinator-delete' type='button' "
            f"aria-label='Delete {kind} {_escape(delete_name)}' title='Delete {kind}' "
            f"data-result-id='{key}' data-kind='{kind}' "
            f"data-display-name='{_escape(delete_name)}' data-path='{_escape(path)}'>"
            "<svg class='coordinator-trash-icon' aria-hidden='true' "
            "width='14' height='14' viewBox='0 0 24 24' fill='none' "
            "stroke='currentColor' stroke-width='1.8' stroke-linecap='round' "
            "stroke-linejoin='round'>"
            "<path d='M4 6h16M9 6V4h6v2M6 6l1 14h10l1-14M10 10v7M14 10v7'/>"
            "</svg></button>"
        )

    def attempt_card(name, group):
        dates = sorted(run.started for run in group if run.started)
        if not dates:
            date_text = "Unknown"
        elif len(dates) == 1:
            date_text = dates[0]
        else:
            date_text = f"{dates[0]} – {dates[-1]}"
        patch_path = group[0].patch_path
        attempt_name, separator, revision = name.partition("@")
        if not separator:
            attempt_name, revision = "", name
        heading = (
            "<div style='min-width:0;overflow-wrap:anywhere'>"
            "<span style='color:#667;font-weight:normal'>Attempt: </span>"
            f"<b>{controls('attempt', group[0].path.parent, attempt_name, suffix=('@' if attempt_name else ' · ') + _escape(revision), delete_name=name)}</b> "
            f"<span style='color:#666'>· {len(group)} {_plural('run', len(group))}"
            f" · {_escape(date_text)}</span></div>"
        )
        if patch_path:
            try:
                patch_text = patch_path.read_text(encoding="utf-8")
                patch_content = (
                    "<pre style='width:max-content;min-width:100%;"
                    "white-space:pre;margin:8px 0 0'>"
                    f"{_escape(patch_text)}</pre>"
                )
            except OSError as exc:
                patch_content = (
                    f"<span style='color:#a22'>Could not read patch: {_escape(exc)}</span>"
                )
        else:
            patch_content = "<span style='color:#666'>No source patch for this revision.</span>"
        body = (
            "<div class='coordinator-attempt-body' style='box-sizing:border-box;"
            "display:grid;width:100%;max-width:100%;margin-top:16px;"
            "grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:12px'>"
            f"<div style='min-width:0;max-width:100%'>{_runs_table(group, controls)}</div>"
            "<details class='coordinator-patch' open style='box-sizing:border-box;"
            "min-width:0;max-width:100%;align-self:start;"
            "border:1px solid #d5dbe3;padding:6px'>"
            "<summary aria-label='Toggle source patch' style='display:flex;"
            "align-items:center;justify-content:space-between;gap:8px;"
            "list-style:none;cursor:pointer'>"
            "<b class='coordinator-patch-title'>Source patch</b>"
            "<svg class='coordinator-patch-chevron' aria-hidden='true' "
            "width='16' height='16' viewBox='0 0 16 16' "
            "style='flex:none;display:block;transform-box:view-box;"
            "transform-origin:8px 8px'>"
            "<path d='m3 5.5 5 5 5-5' fill='none' stroke='currentColor' "
            "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/>"
            "</svg></summary>"
            "<div style='box-sizing:border-box;width:100%;max-height:520px;"
            "overflow:scroll;scrollbar-gutter:stable'>"
            f"{patch_content}</div></details></div>"
        )
        return (
            "<details class='coordinator-panel coordinator-attempt' open "
            "style='box-sizing:border-box;border:1px solid #a9b7c7;"
            "padding:10px 12px;margin:8px 0;width:100%;min-width:0'>"
            "<summary style='display:flex;align-items:center;justify-content:space-between;"
            "gap:8px;list-style:none;cursor:pointer'>"
            f"{heading}{_panel_chevron()}</summary>{body}</details>"
        )

    def render(_change=None):
        targets.clear()
        grouped = _group_runs(runs, search.value)
        visible = sum(len(group) for _, attempts in grouped for _, group in attempts)
        total_attempts = len({run.path.parent for run in runs})
        summary.value = (
            f"<b>{len(runs)} {_plural('run', len(runs))}</b> · "
            f"{total_attempts} {_plural('attempt', total_attempts)} · "
            f"{len({run.experiment for run in runs})} "
            f"{_plural('experiment', len({run.experiment for run in runs}))}"
            + (f" · {visible} matching {_plural('run', visible)}" if search.value.strip() else "")
        )
        if not grouped:
            cards.html = "No matching runs." if search.value.strip() else "No runs found."
            return
        experiment_cards = []
        for experiment, attempts in grouped:
            count = sum(len(group) for _, group in attempts)
            heading = (
                "<h3 style='margin:0;min-width:0;overflow-wrap:anywhere'>"
                "<span style='color:#667;font-weight:normal'>Experiment: </span>"
                f"{controls('experiment', root / experiment, experiment)} "
                "<small style='font-weight:normal;color:#666'>"
                f"{len(attempts)} {_plural('attempt', len(attempts))} · "
                f"{count} {_plural('run', count)}</small></h3>"
            )
            experiment_cards.append(
                "<details class='coordinator-panel coordinator-experiment' open "
                "style='box-sizing:border-box;border:2px solid #607d9b;"
                "padding:12px 14px;margin:10px 0;width:100%;min-width:0'>"
                + "<summary style='display:flex;align-items:center;"
                "justify-content:space-between;gap:8px;list-style:none;cursor:pointer'>"
                + heading + _panel_chevron() + "</summary>"
                + "<div style='margin-top:16px'>"
                + "".join(attempt_card(name, group) for name, group in attempts)
                + "</div></details>"
            )
        cards.html = "".join(experiment_cards)

    def handle_request(change):
        request = change["new"]
        if not request:
            return
        key = request.get("target")
        response = {"id": request.get("id"), "target": key}
        try:
            kind, path = targets[key]
            if request.get("action") == "rename":
                rename_result(root, kind, path, request.get("name"))
            elif request.get("action") == "delete":
                delete_result(root, kind, path)
            else:
                raise ValueError("Unknown result action.")
        except (KeyError, OSError, ValueError, TypeError) as exc:
            cards.response = {**response, "ok": False, "error": str(exc)}
            return
        cards.response = {**response, "ok": True}
        rescan()

    def rescan(_button=None):
        nonlocal runs
        runs, issues = scan_results(root)
        warnings.value = "<br>".join(_escape(issue) for issue in issues[:10])
        if len(issues) > 10:
            warnings.value += f"<br>…and {len(issues) - 10} more warnings"
        render()

    refresh.on_click(rescan)
    search.observe(render, names="value")
    cards.observe(handle_request, names="request")
    dashboard = widgets.VBox(
        [title, widgets.HBox([search, refresh]), summary, warnings, cards],
        layout=widgets.Layout(width="100%"),
    )
    rescan()
    return dashboard
