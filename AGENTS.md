# Rules

- Read `EMULEBB_WORKSPACE_ROOT\repos\emulebb-tooling\docs\WORKSPACE-POLICY.md`
  before build or test orchestration work; it is authoritative for
  workspace-wide rules.
- This file contains build-repo local deltas only. Do not duplicate branch,
  worktree, setup, dependency, or app-source policy here.
- `python -m emule_workspace` is the authoritative orchestration surface.
- Keep orchestration topology-driven from the generated workspace manifest and
  repo-local `deps.json`.
- Do not add direct app-project build instructions to docs; route operators
  through this repo's supported entrypoints.
