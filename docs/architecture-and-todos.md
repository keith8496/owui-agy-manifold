# Architecture and TODOs

## Goal

Provide Antigravity models within Open WebUI through a native manifold backed by the official `agy acp` CLI. Prioritize capabilities that benefit from OWUI context and UI integration, especially controlled access to OWUI tools. This is a new project, not a port or replacement of `agy-acp-bridge` until the prototype demonstrates value.

## Current decisions

- **OWUI interface:** Start with a Pipe manifold so ACP-backed models can appear in the OWUI model picker.
- **Deliverable:** The final manifold must be a single Python file, without requiring additional project-owned Python modules at runtime. Tests and documentation can be separate; `agy` remains an external runtime prerequisite. Other runtime dependencies and whether a separately deployed service is acceptable remain to be decided.
- **Agent transport:** Use `agy acp` by default. It is a bidirectional JSON-RPC protocol over stdin/stdout with sessions and structured events; both ACP and headless modes use stdio. Headless `stream-json` is a possible fallback only if a concrete ACP limitation justifies it.
- **Core boundary:** Keep process/session management and ACP translation logically independent of the OWUI-specific adapter within the single-file deliverable where practical.
- **Tool integration:** Do not assume ACP tool calls automatically execute OWUI tools. Investigate an explicit MCP adapter and prove authorization and result delivery before broadening tool access.
- **Existing bridge:** Leave it intact during validation. It remains useful for independent OpenAI-compatible clients such as 9router; decide separately whether to retain, replace, or share core logic later.
- **Safety defaults:** No silent model substitution. Deny tool/permission actions when a safe authorization or interactive approval path is unavailable. Keep per-user resource authorization intact; container co-location alone is not authorization.

## Design constraints and open risks

- A Pipe runs within the OWUI Python environment. Directly calling router endpoint functions does not automatically run FastAPI dependency injection or establish user authorization. Prefer narrow, version-aware adapters and test the authorization path.
- ACP subprocesses require bounded concurrency, async-safe stdio, cancellation, timeouts, cleanup, crash handling, and a deployment strategy for multiple OWUI workers. Do not rely on process-local memory for cross-worker session state.
- Conversation-to-ACP mapping must handle branches, edits/regeneration, concurrent turns, missing chat context, restarts, and stale-session cleanup.
- Decide whether ACP workers and credentials live in the OWUI container or a separately isolated service. Keep credentials out of logs and prevent AGY from receiving broad OWUI access.
- OWUI UI event support does not guarantee native rendering of every ACP event. Verify status, tool activity, citations, images, reasoning, and permission prompts individually.
- Verify AGY sandbox behavior in the actual container environment; a successful response does not demonstrate sandbox enforcement. Confirm the desired ACP client identity and account-specific model catalog.
- Decide whether multi-account routing, account health/status, and admin controls are required in the manifold or remain elsewhere.

## Proof-of-concept sequence

1. Create a minimal manifold with a static model list and a single ACP-backed model.
2. Stream plain text; verify request errors, turn cancellation, subprocess cleanup, and bounded concurrency.
3. Add conversation-scoped session behavior and test concurrent users, regeneration/branching, missing chat identity, and OWUI restart.
4. Expose one harmless, read-only OWUI capability through MCP. Verify that a user can access only their own authorized resource, tool results return to the same ACP turn, and cancellation leaves no pending operation. Test a second user is denied access to the first user's resource.
5. Define and test permission behavior: interactive UI approval only where supported; deny by default for API/noninteractive contexts.
6. Verify ACP model/config discovery, account-specific model availability, strict failure when the requested model is unavailable, and sandbox behavior.
7. Only after the above, evaluate image input/output, citations, reasoning controls, richer ACP events, multi-account routing, and whether to retain a standalone OpenAI-compatible API.

## TODO

- [ ] Pin the Open WebUI version/commit targeted by the first prototype and review the local Pipe/manifold contract.
- [ ] Verify the final manifold can be installed and run as a single Python file, with its external prerequisites documented.
- [ ] Confirm AGY ACP protocol/version, CLI installation, client identity behavior, and runtime availability in the intended OWUI deployment.
- [ ] Decide process ownership: ACP workers inside OWUI versus a separately isolated service.
- [ ] Specify account/profile ownership, credential persistence, multi-account routing, and revocation behavior.
- [ ] Prototype static manifold + ACP text streaming + cancellation and cleanup.
- [ ] Design conversation/session identifiers and state persistence, including multi-worker behavior.
- [ ] Prototype one read-only MCP tool with per-user OWUI authorization and result round trip.
- [ ] Define safe permission fallback for requests without interactive UI context.
- [ ] Verify sandbox enforcement and strict requested-model behavior in deployment.
- [ ] Decide whether the 9router/OpenAI-compatible endpoint remains a project requirement.
- [ ] Add reproducible tests and deployment notes before expanding features.

## Reference material

- Existing bridge plan: `/home/u7de088ca/projects/agy-acp-bridge/docs/v2-plan.md`
- Existing bridge implementation: `/home/u7de088ca/projects/agy-acp-bridge/bridge.py`
- Local OWUI source tree: `/home/u7de088ca/projects/open-webui`
- OWUI Pipe docs: `https://docs.openwebui.com/features/extensibility/plugin/functions/pipe/`
- OWUI Tools docs: `https://docs.openwebui.com/features/extensibility/plugin/tools/`
- OWUI Filter docs: `https://docs.openwebui.com/features/extensibility/plugin/functions/filter`
- OWUI Event docs: `https://docs.openwebui.com/features/extensibility/plugin/functions/event`
- OWUI Action docs: `https://docs.openwebui.com/features/extensibility/plugin/functions/action`
