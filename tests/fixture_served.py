"""A service for the served-runs tests (PLAN.md 7b): a key-value store over TCP, in the sandbox's image."""

KV_SERVER = r'''
import os, socketserver
store = {k.lower(): v for k, v in os.environ.items() if k.startswith("KV_")}   # the service's own values
class H(socketserver.StreamRequestHandler):
    def handle(self):
        op, *rest = self.rfile.readline().decode().split(" ", 2)
        if op == "set":
            store[rest[0]] = rest[1].strip()
            self.wfile.write(b"ok\n")
        else:
            self.wfile.write((store.get(rest[0].strip(), "none") + "\n").encode())
socketserver.TCPServer.allow_reuse_address = True
socketserver.TCPServer(("0.0.0.0", 7000), H).serve_forever()
'''

KV = '''import socket
def kv(line):
    with socket.create_connection(("kv", 7000), 5) as s:
        s.sendall((line + "\\n").encode())
        return s.makefile().readline().strip()
'''


def kv_service() -> dict:
    return {"image": "docker.io/library/python:3.12-slim", "command": ["python", "-c", KV_SERVER],
            "ready": "python -c \"import socket; socket.create_connection(('127.0.0.1', 7000), 1)\""}
