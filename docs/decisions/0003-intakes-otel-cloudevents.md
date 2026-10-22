# 0003 Intakes: OpenTelemetry and CloudEvents over HTTP

Status: accepted · 2026-10-22

**Decision.** Telemetry enters as OTLP through the OTel Collector. Everything else (domain events, proposals, findings, blueprints, assertions) enters as CloudEvents over HTTP. Capabilities (MCP, HTTP APIs) are called directly and discovered through the map.

**Why.** OTel traces reveal observed couplings for free, the Collector already fans out, and semantic conventions give resource identity. CloudEvents gives one envelope with protocol bindings.

**Consequences.** Systems without OTel enter through CloudEvents adapters. Extension attributes: `causationid`, `environment`, `claimstatus`, `validtime` (see `schemas/events/cloudevents-extensions.json`).
