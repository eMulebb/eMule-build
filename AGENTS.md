# Rules

- Read `EMULEBB_WORKSPACE_ROOT\repos\emulebb-tooling\docs\WORKSPACE-POLICY.md`
  first; it is authoritative for workspace-wide rules.
- Start from
  `EMULEBB_WORKSPACE_ROOT\repos\emulebb-tooling\docs\reference\AGENT-CHECKLIST.md`
  for the repeatable operating path.

Everything below is this repo's local deltas only:

- `python -m emule_workspace` is the authoritative orchestration surface.
- Keep orchestration topology-driven from the generated workspace manifest and
  repo-local `deps.json`.
- Do not add direct app-project build instructions to docs; route operators
  through this repo's supported entrypoints.
