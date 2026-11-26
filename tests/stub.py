"""A local stand-in for the SDK and events APIs, to test our client code offline.

It exercises transport only. It produces no experiment results.
"""

import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from flagpilot import config


class _LocalServer(ThreadingHTTPServer):
    def server_bind(self):
        # Skip HTTPServer's reverse DNS lookup, which can stall for seconds on macOS.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Stub:
    def __init__(self, in_experiment: bool = True, events_status: int = 202):
        self.events: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path.endswith("/identities/"):
                    variant = int(body["identifier"][-1]) % 2 == 1
                    value = config.VARIANT_VALUE if variant else config.CONTROL_VALUE
                    flag = {
                        "feature": {"id": 1, "name": config.FLAG_NAME},
                        "enabled": True,
                        "feature_state_value": value,
                        "variant": value,
                        "reason": "SPLIT",
                    }
                    if in_experiment:
                        flag["metadata"] = {
                            "experiment": {"id": 7, "name": "stub", "in_experiment": True}
                        }
                    self.reply(200, {"flags": [flag]})
                else:
                    if events_status < 400:
                        stub.events.extend(body["events"])
                    self.reply(events_status, {})

            def reply(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = _LocalServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/"

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()

    def client_args(self) -> dict:
        return {
            "api_url": self.url + "api/v1/",
            "events_api_url": self.url,
            "environment_key": "ser.stub",
        }
