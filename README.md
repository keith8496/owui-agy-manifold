# Open WebUI AGY Manifold

A proof of concept for a native Open WebUI manifold that connects Open WebUI to Antigravity through `agy acp`.

The project is OWUI-first, not a mechanical port of `agy-acp-bridge`. The current milestone validates plain-text ACP streaming as a single-file Pipe. Future work may add conversation handling and explicitly authorized OWUI tools; keep the existing bridge separate unless a later decision changes that scope.

## Project notes

- [Executive summary](docs/EXECUTIVE-SUMMARY.md) — concise bootstrap context for future chats.
- [Architecture and TODOs](docs/architecture-and-todos.md) — decisions, constraints, risks, and staged proof of concept.

## Current status

The single-file manifold is implemented on `feat/acp-streaming-poc` and proposed in [PR #2](https://github.com/keith8496/owui-agy-manifold/pull/2). It streams plain text through `agy acp`, exposes one `gemini-4-hydrogen` picker entry, bounds concurrent turns, and applies timeout and subprocess cleanup safeguards.

The POC was exercised in the target Open WebUI 0.13.5 / AGY 1.5.17 deployment: incremental streaming, Stop/process cleanup, and strict model selection passed. The local fake-process suite has 12 passing tests.

This is for isolated testing, not production. Requests with history, system prompts, tools, or attachments are unsupported; permission requests are rejected. Sandbox enforcement has not been independently verified, and the POC does not yet implement conversation-scoped sessions or OWUI memory access. See [streaming POC notes](docs/streaming-poc.md) and [architecture and TODOs](docs/architecture-and-todos.md) for acceptance details and next steps. The existing `agy-acp-bridge` remains separate and unchanged.
