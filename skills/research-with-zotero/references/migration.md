# Existing Markdown migration

Prepare and apply a reviewable manifest; never let an LLM mutate Zotero directly.

## Workflow

1. Run the read-only audit and save its compact JSON plan:

   ```bash
   za-cli --session "$session" --json fulltext audit --output migration-plan.json
   ```

2. Accept deterministic classifications only:
   - stored `source.md` and title-like paper Markdown may be Full Text candidates;
   - `distill.md`, `probe_distill.md`, Notes, and Annotations are not candidates;
   - missing linked files and multiple plausible candidates remain unresolved.
3. If subagents are available, an inexpensive read-only subagent may inspect only unresolved plan entries and edit candidate decisions in the plan. It must not call Zotero writes, infer missing paths, or decide without evidence.
4. Show the user counts by decision, exclusions, missing files, and ambiguities. State that only entries with `candidateClass: candidate` will be applied.
5. Obtain explicit user confirmation, then run:

   ```bash
   za-cli --session "$session" --json fulltext migrate migration-plan.json --confirm
   ```

6. Report every success, definite failure, committed warning, and unknown outcome. A partial failure exits nonzero. A lost bridge connection stops the batch because the outcome is unknown; a rollback failure also stops and reports the orphan attachment key. Inspect that item before any retry. Do not retry stale or conflicting items without a new audit and review.

The CLI and Extension revalidate attachment keys, paths, and SHA-256 values. A successful adoption stores unchanged bytes as `fulltext.md`, marks and validates it, and then moves the adopted source and explicitly selected prior Full Text attachments to Trash. One failed item cannot authorize guesses or changes to another.
