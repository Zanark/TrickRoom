# 06 - Development workflow, TODOs and journaling

## Numbered catalogue

`TODO\00_INDEX.todo` is the status landing page. Each stable workstream has a
`NN_UPPER_SNAKE_CASE.todo` file with:

```text
# Scoped workstream

Status: NOT_STARTED
Milestone: M1
Dependencies: 01_FOUNDATION.todo

## Purpose
One outcome.

## Tasks
- [ ] Observable work.

## Acceptance criteria
- [ ] What actually demonstrates completion.

## Completion evidence
- None yet. A planned artifact is not evidence.

## Completion log
- YYYY-MM-DD HH:mm +05:30 - Planned.
```

The form follows existing project prior art, including the numbered catalogue documented in
phantom-fudge. It is not claimed to be a universal format used by every prior repository.

Statuses:

- **NOT_STARTED:** scoped but not being executed.
- **IN_PROGRESS:** active or partially delivered, with remaining acceptance work.
- **BLOCKED:** a concrete dependency/environment/decision prevents attempted completion.
- **DONE:** the workstream's own tasks and acceptance conditions have evidence.

Dependencies are hard prerequisites relative to the containing TODO file. Do not renumber
completed work to insert new tasks. Append a new ID and update dependencies. Preserve failed
attempts and superseded decisions in completion logs/journal.

Engineering completion is separate from live qualification. Workstream 07 can remain BLOCKED
after engineering checks pass. Future Blender and room work are NOT_STARTED, not silently
scheduled for implementation.

## Change procedure

1. Read the affected docs and TODO; set its status IN_PROGRESS before execution.
2. Make the smallest complete source change and cover the behavior/edge cases.
3. Run the relevant tests; escalate to the full small suite when core contracts change.
4. For visible changes, regenerate and inspect synthetic gallery/UI evidence.
5. Update affected guides, source map, journal, TODO tasks/evidence and index together.
6. Record the actual commands, results, environment and remaining limits.

Do not claim an uncommitted working tree is a commit. Artifact hashes and a dated source-tree
digest can identify local evidence; a commit hash is added only when a commit exists.
No commit, push, release or deployment is automatic.

## Journal

Root `JOURNAL.md` is a newest-first technical development ledger. Include:

- what was attempted and why;
- actual errors and diagnosis, including failed hypotheses;
- changes made in response;
- measured results with their evidence class;
- what remains unverified.

Avoid dumping terminal transcripts. Never log source addresses, camera credentials, raw media,
landmark streams or personal details. Aggregate counts/timings and original synthetic visuals
are enough for most engineering changes.

## Local context continuity

The ignored `.agent-context` store holds this base's README, STATE, MEMORY and JOURNAL. It
cross-references canonical historical material rather than copying sibling stores. Refresh
Context Mesh at milestones. Only TrickRoom's store may be updated from this base.

Do not treat stale historical suggestions as automatic next actions. In particular, the older
cardboard avatar's marker/depth experiments and Blender cover-scene workflow are references,
not a backlog to execute in this repository.
