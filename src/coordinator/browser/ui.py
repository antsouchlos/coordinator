import html
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from coordinator.browser import (
    delete_result,
    load_selected,
    make_figure,
    rename_result,
    scan_results,
)
from coordinator.browser.settings import (
    PANEL_DEFAULTS,
    get_default_settings_path,
    load_settings,
    make_default_settings,
    remap_paths,
    save_settings,
)
from coordinator.results import get_results_root


class _ComparisonFigure(go.FigureWidget):
    _css = """
    .coordinator-comparison-figure {
        display: block;
        box-sizing: border-box;
        width: 100% !important;
        min-width: 0;
    }
    """


def _escape_html(value):
    return html.escape(str(value))


def _pluralize(word, count):
    return word if count == 1 else f"{word}s"


def _split_label_and_id(dirname):
    label, separator, identity = dirname.rpartition("@")
    return (label, identity) if separator else ("", dirname)


def _render_panel_chevron():
    return (
        "<svg class='coordinator-panel-chevron' aria-hidden='true' "
        "width='16' height='16' viewBox='0 0 16 16' "
        "style='flex:none;display:block;transform-box:view-box;transform-origin:8px 8px'>"
        "<path d='m3 5.5 5 5 5-5' fill='none' stroke='currentColor' "
        "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/></svg>"
    )


def _render_escaped_data_table(run):
    try:
        frame = pd.read_csv(run.path / "data.csv")
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        return f"<span style='color:#a22'>Could not read data.csv: {_escape_html(exc)}</span>"

    return frame.to_html(index=False, escape=True, border=0, na_rep="")


def _render_runs_table(group, render_controls, selected, render_panel_attributes):
    params = sorted({key for run in group for key in run.params})
    shared = sorted({key for run in group for key in run.shared})
    header_style = "text-align:left;padding:5px 7px;border-bottom:2px solid #c8d1db;white-space:nowrap"
    cell_style = "padding:5px 7px;border-bottom:1px solid #e3e8ed;white-space:nowrap"
    headers = ["Run", *params, *(f"Sweep: {key}" for key in shared), "Axis", "Started"]
    sweep_path = group[0].path.parent
    all_selected = all(run.path in selected for run in group)
    select_all = (
        "<label class='coordinator-select-label'>"
        f"<input class='coordinator-select' type='checkbox' data-select-kind='sweep' "
        f"data-select-path='{_escape_html(sweep_path)}' aria-label='Select all runs in sweep {_escape_html(sweep_path.name)}'"
        + (" checked" if all_selected else "")
        + "> Run</label>"
    )
    rows = [
        "<tr><th style='"
        + header_style
        + "'>"
        + select_all
        + "</th>"
        + "".join(
            f"<th style='{header_style}'>{_escape_html(label)}</th>"
            for label in headers[1:]
        )
        + "</tr>"
    ]

    for run in group:
        metadata = json.dumps(run.metadata, indent=2, sort_keys=True, default=str)
        label, identity = _split_label_and_id(run.path.name)
        values = [
            "<span class='coordinator-select-label'>"
            f"<input class='coordinator-select' type='checkbox' data-select-kind='run' "
            f"data-select-path='{_escape_html(run.path)}' aria-label='Plot run {_escape_html(run.label)}'"
            + (" checked" if run.path in selected else "")
            + ">"
            f"<b>{render_controls('run', run.path, label, suffix=('@' if label else ' · ') + _escape_html(identity), delete_name=run.path.name)}</b>"
            "</span>"
            "<div style='display:flex;gap:12px;margin-top:3px'>"
            f"<details class='coordinator-view-data' {render_panel_attributes('data', run.path)}>"
            "<summary style='cursor:pointer;color:#38638a'>View data</summary></details>"
            f"<details class='coordinator-view-metadata' {render_panel_attributes('metadata', run.path)}>"
            "<summary style='cursor:pointer;color:#38638a'>View metadata</summary></details>"
            "</div>",
            *(
                _escape_html(run.params[key]) if key in run.params else "—"
                for key in params
            ),
            *(
                _escape_html(run.shared[key]) if key in run.shared else "—"
                for key in shared
            ),
            _escape_html(run.axis),
            _escape_html(run.started),
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
            f"{_render_escaped_data_table(run)}</div></td></tr>"
        )
        rows.append(
            "<tr class='coordinator-run-metadata'><td "
            f"colspan='{len(headers)}' style='max-width:0;padding:8px 7px;"
            "border-bottom:1px solid #e3e8ed'>"
            f"<code style='display:block;white-space:normal;overflow-wrap:anywhere'>"
            f"{_escape_html(run.path)}</code>"
            "<pre style='white-space:pre-wrap;overflow-wrap:anywhere'>"
            f"{_escape_html(metadata)}</pre></td></tr>"
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
    term = term.casefold().strip()
    experiments = defaultdict(lambda: defaultdict(list))

    for run in runs:
        attempt = run.path.parent.parent.name
        content = json.dumps(
            {"label": run.label, "params": run.params, "shared": run.shared},
            default=str,
        ).casefold()

        if term and not any(
            term in value
            for value in (
                run.experiment.casefold(),
                attempt.casefold(),
                run.sweep.casefold(),
                content,
            )
        ):
            continue

        experiments[run.experiment][attempt].append(run)

    return [
        (
            experiment,
            [
                (
                    attempt,
                    sorted(group, key=lambda run: (run.label.casefold(), run.identity)),
                )
                for attempt, group in sorted(
                    attempts.items(),
                    key=lambda item: (max(run.started for run in item[1]), item[0]),
                    reverse=True,
                )
            ],
        )
        for experiment, attempts in sorted(experiments.items())
    ]


def launch_results_browser(
    results_root: Path | str | None = None,
    settings_path: Path | str | None = None,
):
    """Return a results overview with persistent settings for JupyterLab."""
    try:
        import ipywidgets as widgets
    except ImportError as exc:
        raise ImportError(
            "Install ipywidgets in this notebook's kernel (for example, pip install ipywidgets)."
        ) from exc

    try:
        from coordinator.browser.widget import ResultsOverview
    except ImportError as exc:
        raise ImportError(
            "Install anywidget in this notebook's kernel (for example, pip install anywidget)."
        ) from exc

    root = (
        Path(results_root).expanduser().resolve()
        if results_root
        else get_results_root().resolve()
    )
    settings_file = (
        Path(settings_path).expanduser().resolve()
        if settings_path
        else get_default_settings_path(root)
    )
    settings_error = ""
    settings_writable = True

    try:
        settings = load_settings(settings_file)
    except (OSError, ValueError, TypeError) as exc:
        settings = make_default_settings()
        settings_error = f"Could not load browser settings from {settings_file}: {exc}. Automatic saving is disabled."
        settings_writable = False

    runs = []
    scan_issues = []
    selected = {root / path for path in settings["selected_runs"]}
    targets = {}

    title = widgets.HTML("<h2 style='margin:0'>Simulation results</h2>")
    plot_area = widgets.VBox()
    plot_area.layout = widgets.Layout(
        width="100%", min_width="0px", display="none", margin="0 0 28px 0"
    )
    plot_area.add_class("coordinator-plot-area")

    metric = widgets.Dropdown(description="Metric:")
    metric.layout = widgets.Layout(width="300px", margin="0 20px 0 0")
    logx = widgets.Checkbox(
        description="Log X", indent=False, value=settings["plot"]["logx"]
    )
    logy = widgets.Checkbox(
        description="Log Y", indent=False, value=settings["plot"]["logy"]
    )
    logx.layout = widgets.Layout(width="auto", flex="0 0 auto", margin="0")
    logy.layout = widgets.Layout(width="auto", flex="0 0 auto", margin="0 0 0 8px")
    plot_controls = widgets.HBox([metric, logx, logy])
    plot_controls.layout = widgets.Layout(align_items="center", margin="0 0 12px 0")

    summary = widgets.HTML()
    search = widgets.Text(
        placeholder="Search experiments, attempts, sweeps, runs, parameters"
    )
    search.layout = widgets.Layout(width="min(560px, 75%)")
    refresh = widgets.Button(description="Refresh", icon="refresh")
    warnings = widgets.HTML()
    cards = ResultsOverview()
    cards.layout = widgets.Layout(width="100%", min_width="0px")

    def update_warnings(issues=None):
        messages = [settings_error] if settings_error else []
        messages.extend(issues or [])
        warnings.value = "<br>".join(_escape_html(message) for message in messages[:10])

        if len(messages) > 10:
            warnings.value += f"<br>…and {len(messages) - 10} more warnings"

    def persist_settings():
        nonlocal settings_error

        if not settings_writable:
            return

        try:
            save_settings(settings_file, settings)
        except OSError as exc:
            settings_error = (
                f"Could not save browser settings to {settings_file}: {exc}"
            )
            update_warnings(scan_issues)
        else:
            if settings_error:
                settings_error = ""
                update_warnings(scan_issues)

    def get_relative_path(path):
        return path.relative_to(root).as_posix()

    def render_panel_attributes(kind, path):
        key = get_relative_path(path)
        opened = settings["panels"][kind].get(key, PANEL_DEFAULTS[kind])
        return (
            f"data-panel-kind='{kind}' data-panel-path='{_escape_html(key)}' "
            f"data-initial-open='{str(opened).lower()}'" + (" open" if opened else "")
        )

    def get_selection_state():
        attempts = defaultdict(list)
        sweeps = defaultdict(list)

        for run in runs:
            attempts[str(run.path.parent.parent)].append(run.path)
            sweeps[str(run.path.parent)].append(run.path)

        return {
            "runs": sorted(str(path) for path in selected),
            "sweeps": {
                path: (
                    "all"
                    if all(run in selected for run in group)
                    else "some"
                    if any(run in selected for run in group)
                    else "none"
                )
                for path, group in sweeps.items()
            },
            "attempts": {
                path: (
                    "all"
                    if all(run in selected for run in group)
                    else "some"
                    if any(run in selected for run in group)
                    else "none"
                )
                for path, group in attempts.items()
            },
        }

    def update_plot():
        if not selected:
            plot_area.children = ()
            plot_area.layout.display = "none"
            return

        plot_area.layout.display = "flex"
        chosen = [run for run in runs if run.path in selected]

        try:
            axis, loaded, metrics = load_selected(chosen)

            if not metrics:
                raise ValueError("Selected runs have no common numeric metric.")
        except ValueError as exc:
            metric.disabled = True
            plot_area.children = (
                plot_controls,
                widgets.HTML(f"<span style='color:#a22'>{_escape_html(exc)}</span>"),
            )
            return

        metric.disabled = False
        current = (
            metric.value
            if metric.value in metrics
            else (
                settings["plot"]["metric"]
                if settings["plot"]["metric"] in metrics
                else metrics[0]
            )
        )
        metric.unobserve(on_plot_control_change, names="value")

        try:
            metric.options = metrics
            metric.value = current
        finally:
            metric.observe(on_plot_control_change, names="value")

        if settings["plot"]["metric"] != metric.value:
            settings["plot"]["metric"] = metric.value
            persist_settings()

        try:
            figure = _ComparisonFigure(
                make_figure(
                    axis, loaded, metric.value, logx=logx.value, logy=logy.value
                )
            )
            figure.layout.height = 600

            if cards.plot_width:
                figure.layout.width = cards.plot_width

            figure.add_class("coordinator-comparison-figure")
            plot_area.children = (plot_controls, figure)
        except ValueError as exc:
            plot_area.children = (
                plot_controls,
                widgets.HTML(f"<span style='color:#a22'>{_escape_html(exc)}</span>"),
            )

    def on_plot_control_change(_change):
        settings["plot"] = {
            "metric": metric.value,
            "logx": logx.value,
            "logy": logy.value,
        }
        persist_settings()
        update_plot()

    def on_plot_width_change(change):
        if len(plot_area.children) == 2 and isinstance(
            plot_area.children[1], _ComparisonFigure
        ):
            plot_area.children[1].layout.width = change["new"]

    def render_controls(kind, path, name, *, suffix="", delete_name=None):
        key = str(len(targets))
        targets[key] = (kind, path)
        shown = name if name else "Add label"
        delete_name = shown if delete_name is None else delete_name
        edit_action = "Rename" if kind == "experiment" else "Edit"
        edit_subject = kind if kind == "experiment" else f"{kind} label"
        return (
            f"<span class='coordinator-editable' tabindex='0' role='button' "
            f"aria-label='{edit_action} {edit_subject}' data-result-id='{key}' "
            f"data-kind='{kind}' data-edit-name='{_escape_html(name)}'>"
            f"{_escape_html(shown)}</span>"
            f"{suffix}"
            f"<button class='coordinator-delete' type='button' "
            f"aria-label='Delete {kind} {_escape_html(delete_name)}' title='Delete {kind}' "
            f"data-result-id='{key}' data-kind='{kind}' "
            f"data-display-name='{_escape_html(delete_name)}' data-path='{_escape_html(path)}'>"
            "<svg class='coordinator-trash-icon' aria-hidden='true' "
            "width='14' height='14' viewBox='0 0 24 24' fill='none' "
            "stroke='currentColor' stroke-width='1.8' stroke-linecap='round' "
            "stroke-linejoin='round'>"
            "<path d='M4 6h16M9 6V4h6v2M6 6l1 14h10l1-14M10 10v7M14 10v7'/>"
            "</svg></button>"
        )

    def group_sweep_runs(group):
        grouped = defaultdict(list)

        for item in group:
            grouped[item.path.parent.name].append(item)

        return sorted(grouped.items())

    def render_sweep_card(name, group):
        path = group[0].path.parent
        label, identity = _split_label_and_id(name)

        heading = (
            "<span style='color:#667'>Sweep: </span>"
            f"<b>{render_controls('sweep', path, label, suffix=('@' if label else ' · ') + _escape_html(identity), delete_name=name)}</b> "
            f"<span style='color:#666'>· {len(group)} {_pluralize('run', len(group))}</span>"
        )
        return (
            f"<details class='coordinator-panel coordinator-sweep' {render_panel_attributes('sweep', path)} "
            "style='border:1px solid #bcc8d4;padding:8px;margin:8px 0'>"
            "<summary style='display:flex;justify-content:space-between;cursor:pointer'>"
            f"{heading}{_render_panel_chevron()}</summary>"
            + _render_runs_table(
                group, render_controls, selected, render_panel_attributes
            )
            + "</details>"
        )

    def render_attempt_card(name, group):
        dates = sorted(run.started for run in group if run.started)

        if not dates:
            date_text = "Unknown"
        elif len(dates) == 1:
            date_text = dates[0]
        else:
            date_text = f"{dates[0]} – {dates[-1]}"

        patch_path = group[0].patch_path
        attempt_name, revision = _split_label_and_id(name)

        heading = (
            "<div style='min-width:0;overflow-wrap:anywhere'>"
            "<span style='color:#667;font-weight:normal'>Attempt: </span>"
            f"<b>{render_controls('attempt', group[0].path.parent.parent, attempt_name, suffix=('@' if attempt_name else ' · ') + _escape_html(revision), delete_name=name)}</b> "
            f"<span style='color:#666'>· {len(group)} {_pluralize('run', len(group))}"
            f" · {_escape_html(date_text)}</span></div>"
        )

        if patch_path:
            try:
                patch_text = patch_path.read_text(encoding="utf-8")
                patch_content = (
                    "<pre style='width:max-content;min-width:100%;"
                    "white-space:pre;margin:8px 0 0'>"
                    f"{_escape_html(patch_text)}</pre>"
                )
            except OSError as exc:
                patch_content = f"<span style='color:#a22'>Could not read patch: {_escape_html(exc)}</span>"
        else:
            patch_content = (
                "<span style='color:#666'>No source patch for this revision.</span>"
            )

        body = (
            "<div class='coordinator-attempt-body' style='box-sizing:border-box;"
            "display:grid;width:100%;max-width:100%;margin-top:16px;"
            "grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:12px'>"
            f"<div style='min-width:0;max-width:100%'>{''.join(render_sweep_card(name, members) for name, members in group_sweep_runs(group))}</div>"
            f"<details class='coordinator-patch' {render_panel_attributes('patch', group[0].path.parent.parent)} style='box-sizing:border-box;"
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
            f"<details class='coordinator-panel coordinator-attempt' {render_panel_attributes('attempt', group[0].path.parent.parent)} "
            "style='box-sizing:border-box;border:1px solid #a9b7c7;"
            "padding:10px 12px;margin:8px 0;width:100%;min-width:0'>"
            "<summary style='display:flex;align-items:center;justify-content:space-between;"
            "gap:8px;list-style:none;cursor:pointer'>"
            f"{heading}{_render_panel_chevron()}</summary>{body}</details>"
        )

    def render(_change=None):
        targets.clear()
        grouped = _group_runs(runs, search.value)
        visible = sum(len(group) for _, attempts in grouped for _, group in attempts)
        total_attempts = len({run.path.parent.parent for run in runs})
        total_sweeps = len({run.path.parent for run in runs})
        summary.value = (
            f"<b>{len(runs)} {_pluralize('run', len(runs))}</b> · "
            f"{total_attempts} {_pluralize('attempt', total_attempts)} · "
            f"{total_sweeps} {_pluralize('sweep', total_sweeps)} · "
            f"{len({run.experiment for run in runs})} "
            f"{_pluralize('experiment', len({run.experiment for run in runs}))}"
            + (
                f" · {visible} matching {_pluralize('run', visible)}"
                if search.value.strip()
                else ""
            )
        )
        cards.selection = get_selection_state()

        if not grouped:
            cards.html = (
                "No matching runs." if search.value.strip() else "No runs found."
            )
            return

        experiment_cards = []

        for experiment, attempts in grouped:
            count = sum(len(group) for _, group in attempts)
            heading = (
                "<h3 style='margin:0;min-width:0;overflow-wrap:anywhere'>"
                "<span style='color:#667;font-weight:normal'>Experiment: </span>"
                f"{render_controls('experiment', root / experiment, experiment)} "
                "<small style='font-weight:normal;color:#666'>"
                f"{len(attempts)} {_pluralize('attempt', len(attempts))} · "
                f"{count} {_pluralize('run', count)}</small></h3>"
            )
            experiment_cards.append(
                f"<details class='coordinator-panel coordinator-experiment' {render_panel_attributes('experiment', root / experiment)} "
                "style='box-sizing:border-box;border:2px solid #607d9b;"
                "padding:12px 14px;margin:10px 0;width:100%;min-width:0'>"
                + "<summary style='display:flex;align-items:center;"
                "justify-content:space-between;gap:8px;list-style:none;cursor:pointer'>"
                + heading
                + _render_panel_chevron()
                + "</summary>"
                + "<div style='margin-top:16px'>"
                + "".join(render_attempt_card(name, group) for name, group in attempts)
                + "</div></details>"
            )

        cards.html = "".join(experiment_cards)

    def handle_request(change):
        nonlocal selected
        request = change["new"]

        if not request:
            return

        key = request.get("target")
        response = {"id": request.get("id"), "target": key}

        try:
            if request.get("action") == "panel":
                kind = request.get("kind")
                panel_path = request.get("path")
                opened = request.get("open")

                if (
                    kind not in PANEL_DEFAULTS
                    or not isinstance(panel_path, str)
                    or not isinstance(opened, bool)
                ):
                    raise ValueError("Invalid panel state.")

                valid = {
                    "experiment": {
                        get_relative_path(run.path.parent.parent.parent) for run in runs
                    },
                    "attempt": {
                        get_relative_path(run.path.parent.parent) for run in runs
                    },
                    "sweep": {get_relative_path(run.path.parent) for run in runs},
                    "patch": {
                        get_relative_path(run.path.parent.parent) for run in runs
                    },
                    "data": {get_relative_path(run.path) for run in runs},
                    "metadata": {get_relative_path(run.path) for run in runs},
                }

                if panel_path not in valid[kind]:
                    raise ValueError(
                        "Panel is no longer available. Refresh the browser."
                    )

                panels = settings["panels"][kind]

                if panels.get(panel_path, PANEL_DEFAULTS[kind]) != opened:
                    if opened == PANEL_DEFAULTS[kind]:
                        panels.pop(panel_path, None)
                    else:
                        panels[panel_path] = opened

                    persist_settings()

                cards.response = {**response, "ok": True}
                return

            if request.get("action") == "select":
                kind = request.get("kind")
                path = Path(request.get("path"))

                if kind == "run":
                    choices = {run.path for run in runs if run.path == path}
                elif kind == "sweep":
                    choices = {run.path for run in runs if run.path.parent == path}
                elif kind == "attempt":
                    choices = {
                        run.path for run in runs if run.path.parent.parent == path
                    }
                else:
                    raise ValueError("Unknown selection type.")

                if not choices:
                    raise ValueError(
                        "Result is no longer available. Refresh the browser."
                    )

                if request.get("checked") is True:
                    selected.update(choices)
                elif request.get("checked") is False:
                    selected.difference_update(choices)
                else:
                    raise ValueError("Invalid selection state.")

                settings["selected_runs"] = sorted(
                    get_relative_path(path) for path in selected
                )
                persist_settings()
                cards.selection = get_selection_state()
                update_plot()
                cards.response = {**response, "ok": True}
                return

            kind, path = targets[key]

            if request.get("action") == "rename":
                destination = rename_result(root, kind, path, request.get("name"))
                remap_paths(
                    settings, get_relative_path(path), get_relative_path(destination)
                )
                selected = {root / run for run in settings["selected_runs"]}
            elif request.get("action") == "delete":
                delete_result(root, kind, path)
                remap_paths(settings, get_relative_path(path), None)
                selected = {root / run for run in settings["selected_runs"]}
            else:
                raise ValueError("Unknown result action.")
        except (KeyError, OSError, ValueError, TypeError) as exc:
            cards.response = {**response, "ok": False, "error": str(exc)}
            return

        cards.response = {**response, "ok": True}
        persist_settings()
        rescan()

    def rescan(_button=None):
        nonlocal runs, scan_issues
        runs, scan_issues = scan_results(root)

        if root.is_dir():
            selected.intersection_update(run.path for run in runs)
            current = sorted(get_relative_path(path) for path in selected)
            changed = current != settings["selected_runs"]
            settings["selected_runs"] = current
            valid = {
                "experiment": {
                    get_relative_path(run.path.parent.parent.parent) for run in runs
                },
                "attempt": {get_relative_path(run.path.parent.parent) for run in runs},
                "sweep": {get_relative_path(run.path.parent) for run in runs},
                "patch": {get_relative_path(run.path.parent.parent) for run in runs},
                "data": {get_relative_path(run.path) for run in runs},
                "metadata": {get_relative_path(run.path) for run in runs},
            }

            for kind, panels in settings["panels"].items():
                stale = panels.keys() - valid[kind]

                if stale:
                    changed = True

                    for path in stale:
                        del panels[path]

            if changed:
                persist_settings()

        update_warnings(scan_issues)
        render()
        update_plot()

    refresh.on_click(rescan)
    search.observe(render, names="value")
    metric.observe(on_plot_control_change, names="value")
    logx.observe(on_plot_control_change, names="value")
    logy.observe(on_plot_control_change, names="value")
    cards.observe(handle_request, names="request")
    cards.observe(on_plot_width_change, names="plot_width")

    dashboard = widgets.VBox(
        [title, plot_area, widgets.HBox([search, refresh]), summary, warnings, cards],
        layout=widgets.Layout(width="100%"),
    )
    dashboard.add_class("coordinator-dashboard")

    rescan()
    return dashboard
