# Executive Summary

Build a native Open WebUI manifold for Antigravity, using `agy acp` as the agent transport. The goal is deeper OWUI integration—model selection, user/chat context, streaming, and a path for AGY to call authorized OWUI tools—not merely another OpenAI-compatible endpoint.

The final manifold deliverable must be a single Python file. Keep ACP and OWUI responsibilities logically separate within that file; tests and documentation may remain separate. `agy` is an external runtime prerequisite.

Start with a small proof of concept: static model, streamed text, cancellation/cleanup, and one read-only OWUI tool round trip through MCP with per-user authorization. Preserve strict model selection and deny-by-default behavior where UI approval is unavailable. Keep ACP logic separate from the OWUI adapter; leave `agy-acp-bridge` intact while validating this direction.

Key unresolved areas: ACP process/session lifecycle and concurrency, safe access to OWUI internals, MCP/tool authorization, multi-account/profile strategy, and whether a standalone API remains a requirement. See `architecture-and-todos.md` for decisions and next steps.

## Repository Workflow

Work in `~/projects/owui-agy-manifold`. The public GitHub remote is `keith8496/owui-agy-manifold`; the default branch is `master`, not `main`. Check the worktree before editing. Make changes on a feature branch and submit a PR targeting `master`; do not push directly to `master`. PRs are required, but reviewer approval is not.
