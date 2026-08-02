from __future__ import annotations

import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from za_cli.http import request


class LocalHttpTests(unittest.TestCase):
    def test_redirect_is_not_followed_or_given_authorization(self):
        captured = []

        class Target(BaseHTTPRequestHandler):
            def do_GET(self):
                captured.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        target = ThreadingHTTPServer(("127.0.0.1", 0), Target)

        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{target.server_port}/capture")
                self.end_headers()

            def log_message(self, *args):
                pass

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        threads = [
            threading.Thread(target=target.serve_forever, daemon=True),
            threading.Thread(target=redirect.serve_forever, daemon=True),
        ]
        for thread in threads:
            thread.start()
        try:
            response = request(
                redirect.server_port,
                "/bridge",
                headers={"Authorization": "Bearer persistent-secret"},
            )
        finally:
            redirect.shutdown()
            target.shutdown()
            redirect.server_close()
            target.server_close()
        self.assertEqual(response.status, 302)
        self.assertEqual(captured, [])


if __name__ == "__main__":
    unittest.main()
