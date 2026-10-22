# 0002 No message bus in the core

Status: accepted · 2026-10-22

**Decision.** Integration is modeled as couplings with contracts. Transport topology is an optional realization. No bus is part of the core. Zenoh is the default provider only where a bus is needed (ROS 2 cells, edge devices, high-volume fan-out), behind a bridge to the intake.

**Why.** A central bus obscured integration points and discoverability, and MCP/HTTP capabilities do not belong on one. Zenoh still wins where a bus is needed: native ROS 2 (rmw_zenoh), runs down to microcontrollers.

**Superseded ideas.** Zenoh as the spine; NATS/JetStream as the spine.
