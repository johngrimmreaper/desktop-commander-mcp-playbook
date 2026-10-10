"""Readiness must refer to one live managed process, regardless of unrelated HTTP success."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "dcmcp_readiness", ROOT / "roles/dcmcp/files/readiness.py")
ready = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ready)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.identity = (123, "a" * 32, 456)
        self.connection = Mock()
        self.connection.getresponse.return_value.status = 200
        self.state = patch.object(ready, "service_identity", return_value=self.identity)
        self.listener = patch.object(ready, "require_owned_listener")
        self.http = patch.object(ready.http.client, "HTTPConnection", return_value=self.connection)
        self.state.start()
        self.listener.start()
        self.http.start()
        self.addCleanup(patch.stopall)

    def test_ready_owned_listener_and_stable_process_pass(self):
        ready.check("desktop-commander-mcp.service", "127.0.0.1:8787")
        self.connection.request.assert_called_once_with("GET", "/readyz")
        self.connection.close.assert_called_once()

    def test_failed_service_cannot_be_hidden_by_http_200(self):
        ready.service_identity.side_effect = ready.NotReady("The managed service is not running.")
        with self.assertRaises(ready.NotReady):
            ready.check("desktop-commander-mcp.service", "127.0.0.1:8787")
        ready.http.client.HTTPConnection.assert_not_called()

    def test_unrelated_listener_cannot_make_running_service_ready(self):
        ready.require_owned_listener.side_effect = ready.NotReady("Listener is not owned.")
        with self.assertRaises(ready.NotReady):
            ready.check("desktop-commander-mcp.service", "127.0.0.1:8787")
        ready.http.client.HTTPConnection.assert_not_called()

    def test_restart_during_http_check_is_rejected(self):
        ready.service_identity.side_effect = [self.identity, (124, "b" * 32, 457)]
        with self.assertRaises(ready.NotReady):
            ready.check("desktop-commander-mcp.service", "127.0.0.1:8787")

    def test_non_ready_http_response_is_rejected_and_closed(self):
        self.connection.getresponse.return_value.status = 503
        with self.assertRaises(ready.NotReady):
            ready.check("desktop-commander-mcp.service", "127.0.0.1:8787")
        self.connection.close.assert_called_once()

    def test_invalid_service_names_and_remote_addresses_are_rejected(self):
        for unit, address in (("../other.service", "127.0.0.1:8787"),
                              ("valid.service", "0.0.0.0:8787"),
                              ("valid.service", "127.0.0.1:80")):
            with self.subTest(unit=unit, address=address), self.assertRaises(ready.NotReady):
                ready.check(unit, address)
        ready.service_identity.assert_not_called()


if __name__ == "__main__":
    unittest.main()
