# Claude Code Pipeline

A specification-driven build pipeline for Claude Code. Three agents and one deterministic
workflow script: it specifies the work, implements it, verifies the result against the
specification, and hands you a reviewable change with the evidence attached.

Automated verification, human approval. The pipeline proves the change works; you decide
whether it ships. See [Architecture decisions](#architecture-decisions) for why that boundary
sits where it does.

**Version 1.0** · Qaced License · Requires Claude Code

---

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [What it produces](#what-it-produces)
- [Architecture decisions](#architecture-decisions)
- [Configuration](#configuration)
- [Extending it](#extending-it)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)
- [Core principles](#core-principles)

---

## Requirements

| | |
|---|---|
| **Claude Code** | any recent version, in CLI, desktop, web, or an IDE extension |
| **A project** | any language; the pipeline makes no assumptions about your stack |
| **Optional** | a `CLAUDE.md` in your project root — every agent reads it if present |

No dependencies to install, no build step, no configuration file.

---

## Installation

Copy `agents/`, `skills/`, and `workflows/` into the `.claude/` directory at the root of your
project:

```
your-project/
  CLAUDE.md                       # optional, but every agent reads it
  .claude/
    agents/
      planner.md
      implementer.md
      verifier.md
    skills/
      master-orchestrator/
        SKILL.md
    workflows/
      build-pipeline.js
```

`README.md`, `docs/`, `LICENSE`, and `CONTRIBUTING.md` stay with the repository — they are not
copied into your project.

**Verify the install.** Start Claude Code in your project and type `/master-orchestrator`. If
the skill loads, you are done.

---

## Quick start

Invoke the orchestrator with what you want built:

```
/master-orchestrator add rate limiting to the /api/search endpoint
```

The orchestrator routes the request first and states which route it chose and why.

---

## How it works

### Routing

Every request is classified before anything is spawned.

| Route | Path | When |
|---|---|---|
| **Direct** | The orchestrator edits the file itself. No agents, no artifacts. | A single file, under roughly 20 lines, no new dependency, no interface change, nothing security-sensitive, nothing ambiguous. |
| **Pipeline** | The `build-pipeline` workflow runs. | Everything else. |

Most requests route Direct, by design. A three-stage pipeline run against a one-line fix costs
far more than the fix is worth, and routing is the largest cost lever in the system.

A Direct change is escalated to the Pipeline if it touches authentication, authorization,
secrets, or credentials; migrates or deletes data; changes an API other code depends on; or is
genuinely ambiguous.

### The pipeline

| Stage | Agent | Produces |
|---|---|---|
| **Plan** | `planner` | A testable specification — or a set of blocking questions, if the request is ambiguous. |
| **Build** | `implementer` | Code, tests, and a record of the design decisions made along the way. |
| **Verify** | `verifier` | A pass/fail verdict with reproducible failures, and an explicit statement of whether the product was actually executed. |

Build and Verify form a loop, capped at two iterations by default. The loop also exits early
if the same bugs return unchanged twice in a row.

### Worked example

```
> /master-orchestrator the CSV importer should skip blank rows instead of crashing

Pipeline — this changes error-handling behavior and needs a test, so it gets a real gate.

  Plan     planner       -> .claude/team/T001/spec.xml
  Build    implement#1   -> importer.py, test_importer.py
           verify#1      -> fail: blank row at EOF still raises (1 bug)
           implement#2   -> importer.py
           verify#2      -> pass (ran the product: imported a 3-row fixture with 2 blanks)

Passed. Changed: src/importer.py, tests/test_importer.py
Proven: all 4 acceptance criteria, tests green, importer executed against a real fixture.
Not checked: files over ~10k rows, and non-UTF8 encodings.

Ready for your review.
```

You read the diff. You decide. You commit.

### When it stops

**Blocking ambiguity.** If the planner cannot write a correct specification without an
answer, the run halts and the questions come back to you verbatim. Once you answer, the
workflow resumes at the build stage — the specification is not re-planned, so that stage is
not paid for twice.

**A stuck loop.** If the iteration budget is exhausted, or the same failures repeat, the run
returns the full attempt history and a specific decision for you to make. It does not keep
trying.

**A specification defect.** If the verifier finds that the specification itself is wrong — a
criterion that contradicts another, or that cannot be tested as written — the run stops
immediately rather than routing an unfixable problem through the build loop.

---

## What it produces

Every artifact is written to disk under the task's store directory:

```
.claude/team/
  ledger.md                              # task_id | route | stage | status
  <task_id>/
    spec.xml                             # acceptance criteria, edge cases, risks
    impl/iteration-<n>.xml               # files changed, design decisions, commands run
    verification/iteration-<n>.xml       # verdict, criteria checked, reproducible bugs
```

These are the deliverable, not a byproduct. They exist so that reviewing the change takes two
minutes instead of twenty, and they make substantial pull request descriptions.

Add `.claude/team/` to your `.gitignore` if you would rather not keep them in history.

---

## Architecture decisions

Three decisions shape the system. Each is load-bearing, and each has a reason.

### Human approval at the release gate

The pipeline writes code, runs the tests, and executes the product. It does not commit and it
does not push. Release stays a deliberate human act.

An automated agent holding push credentials is an unreviewed write path into your default
branch. That is a supply-chain property of the system, not a convenience feature, and it is
not one worth trading for the seconds it saves.

What the pipeline provides instead is a release decision that takes two minutes rather than
twenty: a specification, a verification report naming every criterion it proved, an explicit
statement of what it did not check, and the exact list of files touched.

### Verification and approval are separate functions

Verification is mechanical and belongs to a machine. Run the tests, drive the affected flow,
reproduce the failure, report it with the exact steps. The pipeline does this and returns
evidence rather than a summary judgment.

Approval is not mechanical. Whether this is the right change, whether it fits the codebase,
whether it is worth its maintenance cost — those are judgments made against context the
pipeline does not hold. A system in which AI-written code is approved by an AI reviewer
against an AI-written specification contains no independent check at any point. Keeping
approval outside the automation is precisely what makes the verification evidence worth
reading.

### The specification carries the design

Implementation is driven by a written, testable specification rather than a separate design
artifact. On the one-to-three-file changes this pipeline targets, a precise specification makes
implementation close to translation, and the rationale a design stage would produce is
captured where it is actually useful: the implementer records each decision it made, and the
alternative it rejected, in its artifact — next to the code that resulted.

Cross-cutting, multi-module work is where a separate design stage earns its cost. The workflow
is ordinary JavaScript; [Extending it](#extending-it) walks through adding one.

### The cost consequence

Every stage is paid for on every run, so every stage has to earn its place. These three do:
specify, implement, verify, with a bounded fix loop between the last two. Nothing in the run
exists to produce a second opinion about work that has already been proven, and nothing in it
spends tokens on a decision that a human is going to make anyway.

---

## Configuration

### Iteration budget

`workflows/build-pipeline.js`:

```js
const MAX = ARGS.max_iterations || 2
```

Raise the default to 3 if your test suites converge slowly, or override it per run:

```js
args: { task_id, request, max_iterations: 3 }
```

### Models

Each agent pins its own model in frontmatter:

```yaml
model: claude-sonnet-5
```

All three ship on Sonnet, which keeps cost per run predictable. The highest-value upgrade is
the **planner** to `claude-opus-5`: it is the shortest stage, and a sharper specification
reduces fix-loop iterations downstream, which is where cost actually accumulates.

---

## Extending it

The system is a foundation and is meant to be edited. Each change below is small on purpose.

### Teach the verifier your stack

The highest-value edit, and the smallest. In `agents/verifier.md`, replace "run the tests"
with your actual command — `pytest -q`, `npm test -- --run`, `go test ./...`. It stops
guessing immediately.

### Make the verifier stricter

`agents/verifier.md` is deliberately narrow: tests, acceptance criteria, and executing the
product. Add a section for what you care about — a coverage threshold, a dependency audit, a
performance budget, an accessibility pass — then add the matching field to `VERIFIER_OUT` in
the workflow so the script can route on it.

Both edits are required. A field added to the schema but not to the agent file arrives empty,
because the agent was never told to produce it.

### Add a stage

To insert a design step between planning and building, in `build-pipeline.js`:

1. Add `{ title: 'Design', detail: '...' }` to `meta.phases`.
2. Write `agents/architect.md`, copying the shape of `planner.md` — including its persistence
   and structured-return section.
3. Add a schema constant and the `agent(...)` call between the Plan and Build phases.
4. Thread the returned path into the implementer's prompt the way `specPath` is.

The workflow is ordinary JavaScript. `agent()` spawns a worker, `phase()` groups the progress
display, `log()` writes a status line, and `schema:` forces the worker to return validated
JSON so the script can branch on it.

Full detail, including the staleness rule a design stage introduces, is in
[docs/TECHNICALDOC.md](docs/TECHNICALDOC.md).

---

## Documentation

| Document | Contents |
|---|---|
| **[docs/TECHNICALDOC.md](docs/TECHNICALDOC.md)** | The execution model in full: the two worker registries, the artifact-store contract, argument handling, every exit the script can take, the resume mechanism, the token model, and a troubleshooting reference. |
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | Rules for contributing changes back to this repository. |
| **[LICENSE](LICENSE)** | Qaced License, version 1.0. |

---

## Contributing

Contributions are governed by **[CONTRIBUTING.md](CONTRIBUTING.md)**, which forms part of the
license. In brief:

- **A named human is accountable.** Every change is submitted by a person who has read and
  understood every line of it and who answers for it in review. AI assistance is permitted and
  must be disclosed in the pull request.
- **Branch and pull request.** No direct commits to the default branch, including one-line
  fixes. Add `qaceddagoat` as reviewer.
- **General improvements only.** If a change helps only your role, domain, or stack, it
  belongs in your own copy. The test: would someone in a completely different domain benefit
  from it?

These rules apply to changes to this repository. Projects you build with the pipeline are
yours.

---

## License

Qaced License, version 1.0. See [LICENSE](LICENSE).

This is proprietary software, not open source. Licensed users may read, modify, and use it in
their own work, including commercial work, and they own what they produce with it. It may not
be redistributed, resold, published, or used to train a model.

---

## Core principles

If you change nothing else, keep these three. They are what makes the system cheap, and what
keeps it honest.

1. **Pass paths, never pasted artifacts.** Every worker reads its inputs from disk. Inline a
   specification into a prompt and cost begins scaling with task size instead of staying flat.

2. **Route before you spawn.** A pipeline run against a one-line fix costs perhaps fifty
   times what the fix is worth. The Direct route exists for a reason.

3. **Keep the loop bounded.** Two iterations and an oscillation check. An unbounded fix loop
   is the most expensive bug you can write into an agent system, because it looks like
   progress.
