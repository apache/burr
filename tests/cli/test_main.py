from unittest.mock import Mock

import requests

from burr.cli import __main__ as cli_main


def test_open_when_ready_uses_timeout_and_retries(monkeypatch):
    ready_response = Mock(status_code=200)
    get = Mock(side_effect=[requests.exceptions.Timeout, ready_response])
    sleep = Mock()
    open_browser = Mock()

    monkeypatch.setattr(cli_main.requests, "get", get)
    monkeypatch.setattr(cli_main.time, "sleep", sleep)
    monkeypatch.setattr(cli_main.webbrowser, "open", open_browser)

    cli_main.open_when_ready("http://localhost:7241", "http://localhost:7241/app")

    assert get.call_count == 2
    get.assert_called_with(
        "http://localhost:7241", timeout=cli_main.SERVER_READY_TIMEOUT_SECONDS
    )
    sleep.assert_called_once_with(1)
    open_browser.assert_called_once_with("http://localhost:7241/app")
