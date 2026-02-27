# Development Workflow (Verified Delivery)

This workflow is the source of truth for task completion in this repository.

## Core Rule

Do not mark a coding task as done without verification evidence.

Required evidence format:

```text
Verification Evidence
- command: <exact command>
  result: PASS|FAIL (exit code <n>, key summary)
```

If a check was not run, list it explicitly with a reason.

## Standard Flow

1. Confirm scope and risk
- Identify affected files and behavior.
- Decide which unit/integration/E2E tests are relevant.

2. Reproduce or baseline
- For bugs: reproduce failure first with a focused test/command.
- For features/refactors: run at least one focused baseline test before edits.

3. Implement change
- Keep changes minimal and scoped to the task.

4. Run focused verification
- Run targeted tests for touched modules first.
- Example: `uv run pytest tests/test_bus.py::test_publish_subscribe -v`

5. Run code quality gates
- Lint: `uv run ruff check .`
- Type check: `uv run mypy .` (or narrowed target with reason)

6. Run E2E verification for coding tasks
- E2E is required for coding tasks.
- Prefer headless runs to avoid extra windows/tabs.
- Run one E2E target at a time when debugging in headed mode.
- E2E fixtures enforce single-tab cleanup and teardown the dashboard subprocess after tests.
- Run relevant E2E tests, at minimum one applicable scenario:
  - `uv run pytest tests/e2e/test_dashboard.py -v`
  - `uv run pytest tests/e2e/test_security.py -v`

7. Final regression decision
- Run broader tests when risk is medium/high or behavior is cross-cutting.
- Example: `uv run pytest`

8. Report with evidence
- Include each executed command, exit code, and concise pass/fail summary.
- Explicitly list skipped checks and why.

## Minimum Completion Criteria

A coding task is complete only when all are true:

- Relevant targeted tests pass.
- Lint passes (or failures are documented and accepted).
- Type checks pass (or narrowed scope is justified).
- At least one relevant E2E test passes.
- Verification evidence is included in the final update.

## Quick Command Set

```bash
uv sync --dev
uv run pytest tests/<target> -v
uv run ruff check .
uv run mypy .
uv run pytest tests/e2e/test_dashboard.py -v
uv run pytest tests/e2e/test_security.py -v
```
