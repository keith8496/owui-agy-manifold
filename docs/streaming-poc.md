# Streaming POC

Target: Open WebUI 0.13.5, AGY 1.5.17, Linux. This milestone is for an isolated test instance, not a production or shared deployment. It does not implement the memory tool. Keep OWUI built-in functions/tools disabled for this model; this POC rejects tool-enabled requests.

## Local verification

Run `python -m unittest discover -s tests -v` with Python 3.11+ and the Open WebUI runtime dependencies Pydantic and Starlette installed. The tests exercise the Pipe with a fake subprocess. A local smoke test also uses the installed AGY and account, but that cannot validate the Open WebUI container environment.

## Container acceptance test

1. In a disposable single-worker OWUI 0.13.5 instance, provision AGY 1.5.17 and a dedicated, authenticated test profile readable by the OWUI runtime user. Check `agy --version` under that user. Do not mount production data or the Docker socket. Do not add privileges just to make sandbox startup succeed.
2. Install `manifold.py` as a Pipe Function and enable it only for a trusted tester. Set `AGY_EXECUTABLE` if the binary is not on the OWUI process PATH. Leave `ACTUAL_MODEL` at `gemini-4-hydrogen-medium`. No other project Python files are required at runtime.
3. Start a fresh chat with no system prompt, tools or attachments. Verify that the picker shows one Hydrogen model. Request several paragraphs of plain text and verify the response appears incrementally. Repeat in another fresh chat and use Stop while it is streaming; verify the AGY subprocess is gone and the next turn works. Test an unavailable model ID and verify it returns an error, not an answer from a different model.
4. Verify sandbox enforcement independently using a disposable fixture with no sensitive data before broadening access. The temporary working directory and denial of ACP permission callbacks do not establish that native AGY tools are disabled or cannot access other paths.

The Pipe creates a new process per turn and rejects requests beyond two active turns per loaded worker. It supports one plain-text user message per request; history, system prompts, files and tools are out of scope. The base picker ID does not change with effort; the exact upstream model variant is an admin setting for now. Do not put credentials in valves, chat, or test logs. The next tool milestone is a synthetic-memory round trip authorized as the current user, with a second-user denial test before using real memories.

## OWUI acceptance results

Tested in the target OWUI deployment with AGY installed in the container:

- Incremental text streaming: pass.
- Stop and AGY subprocess cleanup: pass.
- Recovery: soft fail by design. The next prompt sent in the same conversation was rejected with `ACP POC supports one user message; history and system prompts are unsupported.` Start a new chat for the next turn; multi-message history remains out of scope for this build.
- Strict model selection: pass; an invalid upstream model did not silently produce an answer from a fallback model.

Retest recovery after implementing explicit history support. Do not classify the current response as an ACP/process recovery failure: the observed error is the POC's deliberate request-shape guard.

## Opt-in ACP diagnostics

For a disposable test instance, enable the admin valve `DEBUG_ACP_EVENTS` and inspect OWUI container logs for `ACP diagnostic`. It defaults to false. Turn it off after testing. Events report allowlisted update types and tool statuses, plus whether a permission request was received; prompts, tool titles, paths, arguments, results, and AGY stderr are not logged. Permission requests are still rejected. Existing OWUI or AGY logs may have different privacy properties.

To capture AGY diagnostics, create an existing private directory writable only by the OWUI runtime user. Set `AGY_LOG_DIRECTORY` to its absolute path and enable `DEBUG_AGY_LOG_FILE`. The Pipe passes `--log-file <unique-file>` to `agy acp --sandbox`; the log file is created mode 0600 and retained after the turn for manual inspection/removal. AGY logs may contain prompts, paths, tool details, or other sensitive information. Use only disposable test data, inspect locally, redact before sharing, and remove logs promptly. Both valves default off. Do not enable `--dangerously-skip-permissions` in the manifold.

These diagnostics show activity, not proof of sandbox enforcement: a failed tool status does not reveal the cause or identify which path was accessed, and an absent event does not prove denial. Use isolated fixtures and independent observation for positive and negative controls. The POC does not capture stderr or preserve the temporary workspace.

## Next-phase boundary

The [session boundary decision](session-boundary.md) retains the single-message guard; session resumption and a memory round trip are not implemented. The synthetic source-handler spike is not a deployment acceptance test. Existing deployment results above apply to the unchanged streaming POC only.
