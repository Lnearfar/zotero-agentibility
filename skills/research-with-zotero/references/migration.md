# Existing Markdown migration

Prepare and apply a reviewable manifest; never let an LLM mutate Zotero directly.

## Workflow

1. Run the read-only audit and save its compact JSON plan:

   ```bash
   zotero-cli --session "$session" --json fulltext audit --output migration-plan.json
   ```

2. Accept deterministic classifications only:
   - stored `source.md` and title-like paper Markdown may be Full Text candidates;
   - `distill.md`, `probe_distill.md`, Notes, and Annotations are not candidates;
   - missing linked files and multiple plausible candidates remain unresolved.
3. If subagents are available, an inexpensive read-only subagent may inspect only unresolved plan entries and edit candidate decisions in the plan. It must not call Zotero writes, infer missing paths, or decide without evidence.
4. Show the user counts by decision, exclusions, missing files, and ambiguities.
5. Stop after the reviewed plan. Version 0.1.0 does not implement `fulltext migrate` and must not modify Zotero through another route.

A later apply command must revalidate attachment keys, paths, and SHA-256 values. A successful adoption will store unchanged bytes as `fulltext.md`, mark it as canonical, validate it, and then move the replaced candidate to Trash. One failed item cannot authorize changes to another.
