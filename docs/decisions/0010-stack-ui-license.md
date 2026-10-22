# 0010 Stack, UI shell and license

Status: accepted · 2026-10-22

**Decision.**
- Python 3.12 with uv.
- UI: Alpine.js + daisyUI window-manager shell. Views (our panels and third-party UIs such as cognee's UI, database consoles, Grafana) are catalog entries launched into windows. Caddy is the gateway: reverse proxy per view on subdomains, `forward_auth` SSO, per-route header rewrites for framing.
- Local deploy: Docker Compose.
- License: Apache-2.0 (matches cognee).

**Parked.** A NATS + JetStream realtime web framework: a separate project; could plug in later as a transport provider.
