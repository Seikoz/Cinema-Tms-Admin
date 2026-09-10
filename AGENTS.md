# Cinema TMS Admin repository workflow

This repository uses GitHub `Seikoz/Cinema-Tms-Admin` `main` as the single source of truth.

Before changing files:

1. Run `git status --short --branch`.
2. Run `git fetch origin main` and inspect `git log --oneline HEAD..origin/main`.
3. When the worktree is clean, run `git pull --ff-only origin main`.
4. If the worktree is dirty or branches diverged, preserve the changes and report the conflict. Never reset, overwrite, or force-push them.

After changing files:

1. Run the relevant tests; for general changes use `.\.python\python.exe -m unittest discover -s automated_tests -p "test_*.py"`.
2. Confirm `data/`, `.python/`, `.venv/`, `dist/`, databases, private keys, credentials, and environment files are not staged.
3. Commit the verified source changes with a concise message.
4. Push with `git push origin main` and verify `origin/main...main` is `0 0`.

Never use `git push --force` or `git reset --hard`. Operational `data\licenses.db` is transferred only as a separate encrypted backup while the license manager is fully closed.

## Mandatory GitHub upload completion gate

The user requires commit and push after every requested source, documentation, or configuration-template change. This is not optional and a local commit alone is not completion.

- Verify the task, inspect for secrets, explicitly stage only the task's safe files, commit, push, and verify `git rev-list --left-right --count HEAD...origin/main` is `0 0`.
- Report the commit and confirmed upload status. Do not report the change as fully complete while its commit remains unpushed.
- If authentication, network, approval, conflicts, or usage limits prevent pushing, preserve the local work and clearly report **GitHub upload incomplete**, the cause, and the remaining action. Never bypass safeguards, force-push, or claim an upload succeeded without evidence.
- Routine commit/push is already requested by the user; additional routine confirmation is unnecessary unless security, scope, or tool approval requirements demand it. An explicit later instruction not to push takes precedence. Read-only tasks do not require empty commits.
- Keep operational data, private keys, passwords, tokens, runtime folders, and build artifacts out of the source repository. Do not include unrelated user edits. Release publication is a separate workflow, not a prerequisite to uploading source.
- Update README/handoff when applicable. Documentation-only changes do not require a program version bump.
- Other PCs must pull this AGENTS.md before these rules are available there; offline or unsynchronized work cannot be controlled remotely by these instructions.
