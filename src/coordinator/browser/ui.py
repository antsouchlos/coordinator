"""Notebook entry point for the React results browser."""

from pathlib import Path

from coordinator.browser.controller import BrowserController
from coordinator.browser.widget import ResultsBrowserWidget
from coordinator.results import get_results_root


def launch_results_browser(
    results_root: Path | str | None = None,
    settings_path: Path | str | None = None,
) -> ResultsBrowserWidget:
    """Open the results browser in a Jupyter notebook output cell."""
    root = Path(results_root).expanduser().resolve() if results_root else get_results_root().resolve()
    settings = Path(settings_path).expanduser().resolve() if settings_path else None
    return ResultsBrowserWidget(BrowserController(root, settings))
