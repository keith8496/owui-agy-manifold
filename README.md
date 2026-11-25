# Open WebUI AGY Manifold

A local project to explore a native Open WebUI manifold that connects Open WebUI to Antigravity through `agy acp`.

The intended direction is an OWUI-first integration, not a mechanical port of `agy-acp-bridge`. The manifold should make ACP-backed models available in OWUI and, if feasible, let an AGY session invoke explicitly authorized OWUI tools. Keep ACP/session logic separable from the OWUI adapter so a standalone API can be reconsidered without coupling the core to one interface.

## Project notes

- [Executive summary](docs/EXECUTIVE-SUMMARY.md) — concise bootstrap context for future chats.
- [Architecture and TODOs](docs/architecture-and-todos.md) — decisions, constraints, risks, and staged proof of concept.

## Current status

Planning only. No implementation or runtime integration has been verified in this repository. The existing `agy-acp-bridge` remains separate and should not be modified as part of this project without an explicit decision.
