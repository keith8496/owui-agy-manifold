# Session boundary: design decision (not implemented)

Target source: Open WebUI v0.13.5, commit `926f826eaef6179c092a936eede6c7363e425975`; AGY 1.5.17. Source inspection is not a deployment test. This is a proposal for review, not an authorization guarantee.

## Decision

Keep the current fresh-process, one-plain-user-message guard. No durable session or memory tool is enabled. ACP resume across processes, state ownership and deletion are not proven for the target AGY build; OWUI identity injection alone does not authorize a chat locator or establish a durable branch head. Do not replace this with an in-process chat-to-process dictionary. A fresh process currently accepts a single message without identity because it creates no shared persistent session; missing identity must deny any future persistent mapping or memory access.

## Observed input and trust boundaries

In the pinned `backend/open_webui/functions.py`, `generate_function_chat_completion` filters special arguments by the Pipe signature. It provides `__user__` from the OWUI UserModel, plus `__metadata__`, `__chat_id__`, `__message_id__`, `__session_id__`, and `__request__`. The current Pipe does not request identity or these locators. Metadata is removed from the copied body before Pipe invocation. The server constructs metadata with `user_id` from the authenticated user in `main.py`; chat, message, regeneration and socket session locators have client-supplied origins or depend on request handling. These are locators, not authorization or proof of a unique branch. Different invocation paths and background tasks require separate review. Reject missing, malformed, mismatched, unsupported or unverified context; explicitly verify access and history ancestry for the principal. Do not trust a body `user_id`.

Representative *synthetic*, not captured live, shape at the Pipe boundary:

```python
body = {"model": "agy.gemini-4-hydrogen", "stream": True,
        "messages": [{"role": "user", "content": "fixture"}]}
# Optional signature injection, not currently consumed:
__user__ = {"id": "user-a"}
__metadata__ = {"user_id": "user-a", "chat_id": "chat-a",
                "user_message_id": "message-a", "regeneration_message_id": None}
```

History and system prompts, multimodal content, files, and tools remain rejected. The current process receives only the single user text and strict configured model; it does not replay prior turns. Future support must define explicit system-prompt provenance, canonical history and exact per-turn deltas, and reject mismatches instead of duplicating prior prompts or silently dropping roles.

## Required design before persistent sessions

- Key ownership by verified principal, authorized saved conversation and verified immutable branch/head, not chat ID alone; temporary chats, channels, shared chats, API-only requests and background tasks are unsupported until individually specified and authorized. Never derive identity from model output or a client-selected user ID.
- Define a durable transactional registry with encrypted/restricted state, a per-branch distributed lease with fencing, expiration, idempotency keys and ownership revalidation on every turn. Workers must route to a verified owner or safely resume; process-local state is not the source of truth. No storage engine or service is approved yet.
- Serialize turns for a branch. Define completion commit, duplicate/retry handling and response delivery; after a timeout, crash or cancellation with uncertain agent state, quarantine that session, do not replay blindly or assume rollback. A stale lease cannot commit results. Cancellation must stop/reap the process and prevent late callbacks.
- Regeneration and editing fork from the last verified parent, never append to the old head. A branch/fork needs an isolated state or a verified deterministic reconstruction mechanism. Reject if the exact state cannot be reconstructed. Concurrent branch changes and retries require transactional conflict detection.
- On restart or worker loss, recover only after verifying capability, exact AGY version/model, ownership, branch and committed head. Failed or stale resume is an explicit error, not a fresh silent session. Define crash-safe deletion, lease reclamation, retention/expiry, chat deletion and account revocation hooks, including any AGY-owned on-disk state and child-process cleanup. These hooks and the confidentiality of AGY persistence are not yet established.
- Verify whether AGY 1.5.17 advertises and correctly implements ACP session loading/resume across process termination, what it persists, and whether it can branch at an exact point; protocol capability alone is insufficient. Verify native tool sandbox enforcement separately. Any implementation requires fake-ACP tests for all lifecycle cases and a disposable deployment acceptance run.

## Synthetic memory spike

The pinned `routers/memories.py` POST `/search` handler uses `Depends(get_verified_user)`, calls `check_memories_permission`, then fetches rows by `user.id` before applying the requested memory ID and filters. This suggests a narrow read-only candidate, not a license to call the handler directly: direct Python calls bypass FastAPI dependency resolution. Review the real authentication, permission, repository and endpoint path in the target deployment before use. Do not pass credentials to AGY.

`tests/test_memory_spike.py` compiles only the pinned handler and form from a SHA-256-checked source file into an isolated FastAPI app. Its principal, permission check, repository and search function are synthetic; tests exercise request validation, dependency invocation, user-scoped fetch, guessed IDs, denial, cancellation and retry. They do not exercise actual OWUI authentication, database, search semantics, ACP, concurrent cross-chat return routing, or production authorization. No same-turn memory round trip is implemented or proven. Do not use real memories until a reviewed adapter and full synthetic cross-user, cross-chat and same-ACP-turn tests pass.

Run with Python dependencies `fastapi`, `httpx`, `pydantic`, `starlette`, and a checkout of the pinned source:

```sh
OWUI_PINNED_SOURCE=/path/to/open-webui/backend/open_webui \
  PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

Without `OWUI_PINNED_SOURCE`, the synthetic handler tests explicitly skip. An incorrect source hash fails rather than silently testing another version. No target deployment acceptance was repeated for this documentation/test-only phase.
