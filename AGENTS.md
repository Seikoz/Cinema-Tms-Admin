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
