# Contributing

**These rules govern changes to *this repository*. They do not govern how you use the
pipeline in your own projects.**

Use AI as hard as you like in your own work — that is what the pipeline is for. Changes to the
pipeline itself are held to a provenance standard. This document states it, and why.

It forms part of the [LICENSE](LICENSE). Breaking it is a license breach, not a style
disagreement.

---

## 1. A named human is accountable for every change

Every commit, pull request, and review here has a human author who is answerable for it. That
person must have read and understood every line they are submitting, and must be able to
explain why it is correct without referring to the tool that produced it.

This is a standard about accountability, not about tooling. AI assistance is permitted at any
stage — exploring an approach, drafting a change, explaining a stage you do not understand,
writing a test. What is not permitted is submitting work that no human has actually reviewed.

Concretely, no automated system may act as the accountable party. An AI agent may not open,
merge, approve, or review a pull request, push to a branch, tag a release, or change
repository settings under its own authority. A human does those things, under their own name.

### Disclose AI assistance

If AI was used to produce or shape a change, say so in the pull request: what it was used for,
and what you verified yourself. One line is enough.

Disclosure is information, not an admission. It tells a reviewer where to look harder, and it
is the same thing this pipeline asks of its own agents — state what was proven, and state what
was not checked.

### Why the standard exists

The system's argument is that a human stays outside the loop and holds the approval gate. A
repository that argues this and then merges unreviewed automated changes into itself is not
applying its own standard.

There is a second reason, and it is the practical one. Reviewing machine-generated code is a
skill, and it is built by doing it. This is the right place to build it.

---

## 2. Branch and pull request. Always.

No direct commits to the default branch. No exceptions, including for one-line fixes,
including for maintainers.

```
git checkout -b <short-descriptive-name>
# make your change
git add -p                      # stage deliberately; read every hunk
git commit
git push -u origin <branch>
```

Then open a pull request and **add `qaceddagoat` as reviewer**.

This applies to **changes to this repository only**. Your own projects built with the pipeline
are yours — branch them however you want.

### What a pull request must contain

- **What changed and why.** One paragraph. If you cannot explain the why, the change is not
  ready.
- **How you verified it.** Which run you performed, on what project, what you observed.
  "Looks right" is not verification.
- **What you did not check.** Every change has an untested edge. Name yours.
- **Whether AI was used, and for what.** See Section 1.

A pull request stays open until `qaceddagoat` reviews it. Do not merge your own work, and do
not merge someone else's on their behalf.

---

## 3. General improvements only

Contribute what helps **everyone** using the pipeline. Keep what helps **only you** in your own
copy.

The test is simple: *would someone in a completely different domain benefit from this?*

**Belongs here:**

- a bug in the workflow's control flow, or a stage that fails to route correctly
- a clearer explanation in the README, the technical documentation, or an agent file
- a guard that saves tokens or catches a class of failure for everyone
- better error messages, better escalation reasons, better defaults
- a genuine gap in the contract — a return status nothing handles, a field nothing reads

**Does not belong here:**

- your stack's test command hardcoded into the verifier
- your organization's conventions, review checklist, or compliance requirements
- a stage that only makes sense for your role, domain, or client
- your model preferences, your budget, your directory layout
- anything that assumes a framework, language, or tool the pipeline does not already assume

That second list is not a list of bad ideas. Those are exactly the customizations the system
expects you to make — the README's *Extending it* section exists for them. They just live in
**your** copy.

The system stays small and general on purpose. Small enough to read in one sitting is a
feature, and every role-specific addition spends that budget on someone else's job.

---

## 4. If you are not sure

Open an issue before you open a pull request. Describe the change and ask whether it is
general enough. That costs you five minutes; a rejected pull request costs you an afternoon.
