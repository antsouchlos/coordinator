"""Small anywidget bridge; browser state lives in BrowserController and React."""

from pathlib import Path

import anywidget

from coordinator.browser.controller import BrowserController

_STATIC = Path(__file__).parent / "static"


class ResultsBrowserWidget(anywidget.AnyWidget):
    _esm = _STATIC / "index.js"
    _css = _STATIC / "index.css"

    def __init__(self, controller: BrowserController):
        self.controller = controller
        super().__init__()
        self.on_msg(self._handle_message)

    def _handle_message(self, _widget, message: dict, _buffers) -> None:
        request_id = message.get("id")
        action = message.get("action")
        payload = message.get("payload") or {}
        try:
            if not isinstance(payload, dict):
                raise ValueError("Invalid browser request.")
            result = self.controller.dispatch(action, payload)
            self.send({"id": request_id, "ok": True, **result})
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.send({"id": request_id, "ok": False, "error": str(exc)})
