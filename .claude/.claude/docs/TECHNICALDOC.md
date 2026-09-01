# Technical documentation — `build-pipeline`

How the pipeline actually executes: the registries it draws from, the contract between
stages, every branch the script can take, and where the tokens go.

The [README](../README.md) tells you how to use the system. This tells you how it works, so
you can change it without guessing.

---

## 1. Two registries, one engine

Claude Code resolves workers from two separate places. Confusing them is the most common
mistake when extending this system.

| Directory | Registry | Invoked by | Runs in |
|---|---|---|---|
| `agents/*.md` | subagents | `agentType:` inside a workflow, or the Agent tool | its own isolated context |
| `skills/*/SKILL.md` | skills | the user typing `/name`, or the Skill tool | the current context |

`build-pipeline.js` calls `agentType: 'implementer'`. That resolves from **`agents/`**. A file
at `skills/implementer/SKILL.md` would never be reached by the pipeline — it would only
register a slash command. Put workers in `agents/`. Put entry points in `skills/`.

This system has exactly one skill (`master-orchestrator`) and three agents.

---

## 2. Execution model

```
  user
   |
   v
  /master-orchestrator            <- skill, runs in your context
   |
   |-- Direct:   edits the file itself, no agents, no store
   |
   `-- Pipeline: Workflow({ name: "build-pipeline", args: {...} })
                  |
                  v
              build-pipeline.js   <- deterministic JavaScript, not a prompt
                  |
                  |-- agent("...", { agentType: "planner",     schema: PLANNER_OUT  })
                  |-- agent("...", { agentType: "implementer", schema: IMPL_OUT     })
                  `-- agent("...", { agentType: "verifier",    schema: VERIFIER_OUT })
                          |
                          v
                    returns a status object -> orchestrator routes on it
```

The distinction that matters: **the loop is code, not instruction.** The iteration budget,
the oscillation check, and the escalation conditions are `if` statements. A model cannot
talk its way past them, forget them under context pressure, or decide this run deserves one
more try. That is the whole reason the pipeline lives in a script instead of in the
orchestrator's prompt.

### Workflow script globals

Available inside `build-pipeline.js`, provided by the engine:

| Global | Purpose |
|---|---|
| `args` | the `args` object passed by the caller — **may arrive as a JSON string** (see §3) |
| `agent(prompt, opts)` | spawns a subagent; returns its validated JSON, or `null` if it died |
| `phase(title)` | starts a progress group; must match a `meta.phases` title to group correctly |
| `log(message)` | writes a narrator line above the progress tree |

`Date.now()`, `Math.random()`, and argless `new Date()` are **unavailable** — they would
break the engine's resume cache. Pass timestamps in through `args` if you need them.

---

## 3. Arguments

```js
Workflow({ name: "build-pipeline", args: {
  task_id,            // required. "T001", "T002", ...
  request,            // required. the user's request, verbatim
  store,              // optional. default `.claude/team/<task_id>`
  answers,            // optional. user answers to a prior clarifications return
  have,               // optional. { spec } — skip the plan on a re-run
  max_iterations,     // optional. default 2
}})
```

**The string/object gotcha.** The engine delivers `args` as a parsed object in some
environments and as a JSON string in others. The script normalizes before use:

```js
ARGS = (typeof args === 'string') ? (args ? JSON.parse(args) : {}) : (args || {})
```

Without this, `args.task_id` reads as `undefined` off a string and the required-args guard
fires on perfectly valid input. If you write your own workflow, copy this block first. It is
the single most confusing failure mode in the engine, because the error blames your input.

---

## 4. The artifact store

```
.claude/team/
  ledger.md                              # task_id | route | stage | status
  <task_id>/
    spec.xml                             # planner
    impl/iteration-<n>.xml               # implementer
    verification/iteration-<n>.xml       # verifier
```

### The contract

Every worker **writes its own full XML artifact to disk** at the path named in its prompt,
then returns **only** a small JSON object. Prompts carry *paths*, never pasted artifacts.

This is not a stylistic preference. It is the cost model:

- **Paths:** the orchestrator's context stays flat no matter how large the task grows. A
  40-criterion spec costs the same to hand off as a 4-criterion one.
- **Pastes:** every artifact is re-sent through every subsequent stage. Cost scales with
  task size *multiplied by* stage count, and it compounds on every fix-loop iteration.

The rule to keep: **if you find yourself inlining an artifact into a prompt, write it to
disk and pass the path instead.**

### Why the JSON return is separate from the XML

The workflow script routes on JSON fields — `verdict`, `blocked_reason`, `owner` — and
**never reads the XML on disk**. The XML is for humans and for the next worker; the JSON is
for the script's control flow.

The practical consequence, and it bites people: if a schema requires `bugs[]`, the worker
must populate `bugs[]` in the JSON *even though* the same bugs are already in its XML file.
A worker that writes a thorough report to disk and returns an empty `bugs[]` will be routed
as though it found nothing. Every agent file states this explicitly; keep that wording if you
write a new one.

---

## 5. Stage reference

### Phase: Plan

Runs once. Skipped entirely if `args.have.spec` is present.

| Return | Meaning | Script action |
|---|---|---|
| `result: "spec"` | spec written to disk | store `spec_path`, continue to Build |
| `result: "clarifications"` | blocking ambiguity | return `blocked_on_user` with the questions |
| `null` (agent died) | schema-retry cap or crash | return `failed` |

A clarifications return is a **hard stop**, by design. The planner gets exactly one round
trip with the user, which is why `agents/planner.md` insists on asking every blocking
question at once rather than dribbling them out.

On the re-run with `args.answers`, the answers are threaded into the planner's prompt as
binding, and planning happens once — not twice.

### Phase: Build

An implementer → verifier loop, up to `MAX` (default 2) iterations.

**Implementer**, per iteration:

- reads the spec from disk, plus the prior verification report on a fix loop
- writes code, writes `impl/iteration-<n>.xml`
- returns `touched_files[]` and `blocked_reason`

`touched_files` is load-bearing: the verifier checks exactly that list. A file omitted from
it is a file that ships unverified.

**Verifier**, per iteration:

- reads the spec and the touched files
- runs the tests, and — if there is a runnable surface — actually starts the product and
  drives the affected flow
- writes `verification/iteration-<n>.xml`
- returns `verdict`, `ran_the_product`, and `bugs[]`

`ran_the_product` is reported honestly as `yes` / `no` / `not-applicable` rather than
silently skipped, so you can tell the difference between "tests pass" and "I watched it
work." It is surfaced to you rather than gated on — see §9 if you want it binding.

**Bug ownership** has exactly two values:

- `implementer` — a code defect. Goes back through the fix loop.
- `planner` — the *spec itself* is wrong: a criterion that contradicts another, or that
  cannot be tested as written. Writing more code cannot fix this, so it stops the run
  immediately and returns to you.

---

## 6. Every exit

The script can only end in one of these. There are no other paths out.

### `passed`

```js
{ status: 'passed', task_id, spec_path, verification_path,
  ran_the_product, touched_files, iterations }
```

The verifier returned `pass`. This means **verified, not approved** — approval and release
are the user's call, by design (README, *Architecture decisions*).

### `blocked_on_user`

```js
{ status: 'blocked_on_user', task_id, stage: 'plan', clarifications: [...] }
```

Only reachable from the Plan phase. The orchestrator shows the questions verbatim and
re-runs with `args.answers`.

### `escalated`

Four distinct conditions, each with its own `unresolved_issue` and `decision_needed`:

| Condition | `stuck_between` | Trigger |
|---|---|---|
| Implementer blocked | `implementer <-> orchestrator` | `blocked_reason !== 'none'` — the spec is impossible, contradictory, or a dependency does not exist |
| Spec defect | `planner <-> orchestrator` | any bug with `owner: 'planner'` |
| Oscillation | `implementer <-> verifier` | identical bug descriptions on two consecutive iterations |
| Budget exhausted | `implementer <-> verifier` | the loop hit `MAX` without a pass |

All four carry `attempts[]` (what was tried each iteration and why it failed) and
`have: { spec }`.

**On the oscillation guard:** it compares a sorted join of bug descriptions against the
previous iteration's. Two identical failures mean the implementer is circling — a third
attempt buys nothing but tokens. This is the cheapest guard in the script and the one that
matters most if you raise `max_iterations`, because budget exhaustion alone will let a stuck
loop run to the cap.

### `failed`

Infrastructure, not logic: a worker returned `null` (died, or hit the schema-retry cap), or
`args` was not valid JSON. Retry once. If `args was not valid JSON`, fix the args — do not
retry unchanged.

---

## 7. Resume

Every non-passing return carries `have: { spec }`. Pass it straight back:

```js
Workflow({ name: "build-pipeline", args: {
  task_id: "T001",
  request: "<the same request>",
  have: { spec: ".claude/team/T001/spec.xml" },
  max_iterations: 3,
}})
```

The Plan phase is skipped and the run resumes at Build. Without it you re-plan and re-pay
for a spec that is already sitting on disk, unchanged.

The resume contract is deliberately minimal — one field, because there is exactly one
expensive artifact produced before the loop. If you add stages (§9), extend `have` with their
outputs and skip them on the same condition; the mechanism does not change, the object just
carries more.

---

## 8. Where the tokens go

Per Pipeline run, at default settings, roughly:

| Stage | Calls | Relative cost | Notes |
|---|---|---|---|
| Plan | 1 | moderate | reads spec inputs, writes the spec |
| Implement | 1–2 | **highest** | reads spec + code, writes code |
| Verify | 1–2 | moderate | reads spec + touched files, runs tests |

The three levers, in order of impact:

1. **Routing.** A Direct-route request answered by the pipeline costs perhaps fifty times what
   the fix is worth. Getting routing right dominates every other optimization in this
   document.
2. **Iteration count.** A second loop roughly doubles the run. The budget and the oscillation
   guard exist to cap the tail.
3. **Scope discipline.** Every worker prompt carries *"read only the files named in this
   prompt plus CLAUDE.md; do not scan the wider repo."* A worker that greps a large repo from
   cold context can cost more than every other stage combined. Do not weaken this line.

All three agents are pinned to `claude-sonnet-5` in frontmatter, so cost per run is
predictable. The single highest-value upgrade is the **planner** to `claude-opus-5`: it is
the shortest stage, and a sharper spec reduces fix-loop iterations downstream — which is
where the money actually is.

---

## 9. Extending it

### Add a field the script routes on

Two edits, always in this order:

1. Add the field to the schema constant in `build-pipeline.js` (`VERIFIER_OUT`, etc.).
2. Add it to the worker's `agents/*.md` output section **and** to its "return only these
   JSON fields" line.

Skip step 2 and the field arrives empty, because the worker was never told to produce it.

### Make `ran_the_product` binding

Today it is reported. To gate on it, after the pass check:

```js
if (ver.verdict === 'pass' && ver.ran_the_product === 'no') {
  // re-verify once, demanding real execution
}
```

Worth adding if your changes usually have a runnable surface. It costs one extra verifier call
on the runs that need it, and it catches the most common false pass there is: code that reads
correctly and does not run.

### Add a stage

1. Add `{ title: 'Design', detail: '...' }` to `meta.phases`.
2. Write `agents/architect.md` — copy the shape of `planner.md`, including the persistence
   and structured-return section.
3. Add a schema constant and an `agent(...)` call between Plan and Build.
4. Thread the returned path into the implementer's prompt the way `specPath` is.

Then handle staleness: if the spec is ever re-planned, an architecture built against the old
spec is stale and must be re-run before it can gate anything. Skipping that is how a pipeline
starts building confidently against a design nobody checked.

### Teach the verifier your stack

The highest-value edit most people make, and the smallest. In `agents/verifier.md`, replace
"run the tests" with your actual command — `pytest -q`, `npm test -- --run`, `go test ./...`.
It stops guessing immediately.

---

## 10. Troubleshooting

| Symptom | Cause |
|---|---|
| `args.task_id and args.request are required` on valid input | the string/object normalization was removed or edited (§3) |
| A worker's field is always empty | it is in the schema but not in the agent's `.md` (§9) |
| Slash command exists for a worker | a stray `skills/<worker>/SKILL.md`; workers belong in `agents/` (§1) |
| Runs cost far more than expected | routing is sending Direct-route work to the pipeline, or a prompt lost its scope line (§8) |
| Loop always hits the budget | the spec is under-specified — read `attempts[]`; repeated unrelated bugs point upstream to planning |
| `failed: <worker> returned nothing` | agent died or hit the schema-retry cap; usually a schema the worker cannot satisfy as written |

---

## 11. Boundaries of the automation

Three lines the pipeline does not cross. Each is a decision with a reason; the full argument
is in the README's *Architecture decisions*.

- **The pipeline verifies; it does not approve.** The verifier returns evidence — criteria
  met, tests run, failures reproduced — and stops there. Whether the change is the right
  change is judged against context the pipeline does not hold.
- **The pipeline does not commit or push.** There is no Git worker and no write path to a
  branch. Release is a deliberate human act, which keeps every change that reaches the default
  branch one a person chose to put there.
- **The specification carries the design.** Implementation is driven by the spec rather than a
  separate design artifact, and the implementer records its decisions and rejected
  alternatives in `impl/iteration-<n>.xml`.

None of these are technical limits. The workflow is ordinary JavaScript and §9 shows how to
extend it — cross-cutting work in particular is where a design stage starts earning its cost.
Move a boundary when your work genuinely needs it moved, and move it knowingly.
