# Session boundary: design decision (not implemented)

Target source: Open WebUI v0.13.5, commit `926f826eaef6179c092a936eede6c7363e425975`; AGY 1.5.17. Source inspection is not a deployment test. This is a proposal for review, not an authorization guarantee.

## Decision

Keep the current fresh-process, one-plain-user-message guard. No durable session or memory tool is enabled. The intended shared-chat behavior is one AGY conversation per OWUI chat: participants in a shared chat intentionally continue the same conversation, so `__user__.id` is not part of the ACP session key. Open WebUI authorizes the request; the Pipe uses the server-injected `__chat_id__` as the session locator. Missing or unsupported chat context must fail closed rather than create an anonymous persistent session. `__user__.id` remains essential for memory authorization and other per-user data. ACP resume across processes and state deletion are not proven for the target AGY build. Do not replace this guard with an in-process chat-to-process dictionary.

## Observed input and trust boundaries

In the pinned `backend/open_webui/functions.py`, `generate_function_chat_completion` filters special arguments by the Pipe signature. It provides `__user__` from the OWUI UserModel, plus `__metadata__`, `__chat_id__`, `__message_id__`, `__session_id__`, and `__request__`. The current Pipe does not request identity or these locators. Metadata is removed from the copied body before Pipe invocation. The server constructs metadata with `user_id` from the authenticated user in `main.py`; chat, message, regeneration and socket session locators have client-supplied origins or depend on request handling. These are locators, not authorization. For the intended shared-chat session policy, Open WebUI is the authorization boundary for sending a message; the AGY session is keyed by the server-injected `__chat_id__`, not by the calling user. The Pipe must not accept a body-supplied ID in place of injected context. Different invocation paths and background tasks still need review; missing or unsupported chat context must not create or resume a session. Memory reads remain bound to the authenticated `__user__.id`, regardless of shared-chat access.

Representative *synthetic*, not captured live, shape at the Pipe boundary:

```python
body = {"model": "agy.gemini-4-hydrogen", "stream": True,
        "messages": [{"role": "user", "content": "fixture"}]}
# Optional signature injection; future session lookup uses chat_id only:
__user__ = {"id": "user-a"}  # Used to authorize user-scoped memory reads.
__chat_id__ = "chat-a"  # Shared by authorized participants in this chat.
```

History and system prompts, multimodal content, files, and tools remain rejected. The current process receives only the single user text and strict configured model; it does not replay prior turns. Future support must define explicit system-prompt provenance, canonical history and exact per-turn deltas, and reject mismatches instead of duplicating prior prompts or silently dropping roles.

## Required design before persistent sessions

- Intended mapping: one ACP session per server-injected OWUI `__chat_id__`; users authorized by OWUI to send in a shared chat share that AGY conversation. `__user__.id` is not part of the session key, but must scope any memory lookup. Do not substitute client body fields for injected context. Confirm behavior for saved and temporary chats, channels, API-only requests and background tasks before supporting each path.
- First prove AGY can resume the recorded session after its subprocess exits and establish where/how AGY persists its state. Then choose the smallest durable mapping store compatible with the actual worker layout. For a single-worker deployment a small local store may suffice; multiple workers need shared durable state and request routing/resume that has been verified. No database or distributed lock service is selected in this phase.
- Prevent overlapping turns in the same chat from racing one AGY session. Test Stop/cancellation, retries, regeneration and edits against OWUI's actual message history behavior; do not replay the same user turn twice or silently append an edited branch. Start with the simplest per-chat serialization and recovery behavior supported by verified AGY semantics.
- On worker restart, recover only if AGY resume and persisted state are verified; otherwise return a clear error and retain the one-message guard. Define expiry and cleanup, including chat deletion and AGY-owned state. Account revocation is not a session boundary for this shared-chat policy, but memory authorization must always use the current request's user.
- Verify whether AGY 1.5.17 advertises and correctly implements ACP session loading/resume across process termination, what it persists, and whether it can branch at an exact point; protocol capability alone is insufficient. Verify native tool sandbox enforcement separately. Any implementation requires fake-ACP tests for all lifecycle cases and a disposable deployment acceptance run.

## Synthetic memory spike

The pinned `routers/memories.py` POST `/search` handler uses `Depends(get_verified_user)`, calls `check_memories_permission`, then fetches rows by `user.id` before applying the requested memory ID and filters. This suggests a narrow read-only candidate, not a license to call the handler directly: direct Python calls bypass FastAPI dependency resolution. Review the real authentication, permission, repository and endpoint path in the target deployment before use. Do not pass credentials to AGY.

`tests/test_memory_spike.py` compiles only the pinned handler and form from a SHA-256-checked source file into an isolated FastAPI app. Its principal, permission check, repository and search function are synthetic; tests exercise request validation, dependency invocation, user-scoped fetch, guessed IDs, denial, cancellation and retry. They do not exercise actual OWUI authentication, database, search semantics, ACP, concurrent cross-chat return routing, or production authorization. No same-turn memory round trip is implemented or proven. Do not use real memories until a reviewed adapter demonstrates per-request user scoping and same-turn delivery to the correct chat session. Shared-chat participants still receive only memories authorized for the current caller; shared conversation state must never become a way to return another user's private memory.

Run with Python dependencies `fastapi`, `httpx`, `pydantic`, `starlette`, and a checkout of the pinned source:

```sh
OWUI_PINNED_SOURCE=/path/to/open-webui/backend/open_webui \
  PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

Without `OWUI_PINNED_SOURCE`, the synthetic handler tests explicitly skip. An incorrect source hash fails rather than silently testing another version. No target deployment acceptance was repeated for this documentation/test-only phase.
