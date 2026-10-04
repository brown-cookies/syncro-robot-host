<!--
============================================================
FEATURE PR
Use this section for introducing new functionality or behavior.
============================================================
-->

# Feature PR

## Summary

<!-- What are you adding or changing? -->

## Problem

<!-- What problem does this feature solve? -->

## Proposed Solution

<!-- Explain the implementation at a high level. -->

## Scope

<!-- What parts of SYNCRO are affected? -->

* [ ] API
* [ ] Audio
* [ ] Adapters
* [ ] Pipeline
* [ ] Storage
* [ ] ML / Affect
* [ ] Configuration
* [ ] Scripts
* [ ] Tests
* [ ] Dev Tooling
* [ ] CI / Security
* [ ] Documentation

## Behavior

<!-- Describe the expected behavior after this PR. -->

## Testing

* [ ] Unit tests
* [ ] Integration tests
* [ ] Full test suite
* [ ] Coverage reviewed

Commands run:

```text
# Example
uv run poe test-api
uv run poe test-integration
uv run poe test
```

## Dependencies

* [ ] No dependency changes
* [ ] Production dependency added/removed
* [ ] Development dependency added/removed
* [ ] `uv.lock` updated

## Breaking Changes

* [ ] None
* [ ] Yes

<!-- Describe required migration steps if applicable. -->

## Documentation

* [ ] No documentation changes required
* [ ] README updated
* [ ] SETUP updated
* [ ] Other documentation updated

## Checklist

* [ ] Feature is limited to the stated scope
* [ ] Existing behavior was preserved where required
* [ ] Tests cover the new behavior
* [ ] No secrets or credentials were committed
* [ ] Unrelated changes were not included

<!--
============================================================
ARCHITECTURE REVIEW PR
Use this section when proposing or reviewing a structural change.
The goal is design discussion, not merely implementation review.
============================================================
-->

# Architecture Review PR

## Proposal (Engineering Review _`techdocs/ARCHITECTUREREVIEW${N}.md`_)

<!-- What architectural change are you proposing? -->

## Current Architecture

<!-- Describe the current design and its limitations. -->

## Proposed Architecture

<!-- Describe the proposed design. Add diagrams when useful. -->

```text
Current:

...

Proposed:

...
```

## Motivation

<!-- Why is the current architecture insufficient? -->

## Design Decisions

### Decision 1

<!-- What decision is being made and why? -->

### Decision 2

<!-- What alternatives were considered? -->

## Alternatives Considered

| Option | Advantages | Disadvantages | Decision |
| ------ | ---------- | ------------- | -------- |
|        |            |               |          |
|        |            |               |          |

## Boundaries Affected

* [ ] API
* [ ] Audio
* [ ] Adapters
* [ ] Pipeline
* [ ] Storage
* [ ] ML / Affect
* [ ] Configuration
* [ ] Runtime
* [ ] Dev Tooling
* [ ] CI / Security
* [ ] Deployment

## Risks

<!-- Technical, operational, security, performance, or maintenance risks. -->

## Migration Strategy

<!-- How do we move from the current architecture to the proposed one? -->

## Compatibility

* [ ] Backward compatible
* [ ] Requires migration
* [ ] Breaking change

## Review Questions

<!-- Explicit questions you want reviewers/architects to answer. -->

1.
2.
3.

## Decision

* [ ] Approved
* [ ] Approved with changes
* [ ] Needs further discussion
* [ ] Rejected

<!-- Do not use this section for ordinary feature implementation PRs. -->

<!--
============================================================
FIX PR
Use this section for bug fixes, regressions, and corrective work.
============================================================
-->

# Fix PR

## Bug

<!-- What is broken? -->

## Reproduction

<!-- Explain how the problem can be reproduced. -->

```text
Steps:

1.
2.
3.
```

## Root Cause

<!-- What caused the bug? -->

## Fix

<!-- What was changed to correct the problem? -->

## Regression Risk

<!-- What existing behavior could potentially be affected? -->

## Testing

* [ ] Regression test added
* [ ] Unit tests
* [ ] Integration tests
* [ ] Relevant subsystem tests
* [ ] Full test suite

Commands run:

```text
# Example
uv run poe test-api
uv run poe test-pipeline
uv run poe test
```

## Dependencies

* [ ] No dependency changes
* [ ] Dependency changes included
* [ ] `uv.lock` updated

## Security Impact

* [ ] None
* [ ] Reviewed

## Checklist

* [ ] Root cause is understood
* [ ] Fix addresses the root cause
* [ ] Regression coverage was added where appropriate
* [ ] No unrelated refactoring was included
* [ ] Existing behavior remains intact where expected

<!--
============================================================
DOCS PR
Use this section for documentation-only changes.
No application behavior should change.
============================================================
-->

# Docs PR

## Documentation Change

<!-- What documentation is being changed? -->

## Reason

<!-- Why does this documentation need to change? -->

## Affected Documentation

* [ ] README
* [ ] SETUP
* [ ] Architecture documentation
* [ ] API documentation
* [ ] Development documentation
* [ ] CI / Security documentation
* [ ] Other

## Accuracy

* [ ] Commands were verified
* [ ] Configuration examples were verified
* [ ] Paths and filenames were verified
* [ ] No outdated instructions remain

## Code Changes

* [ ] No application code changed
* [ ] Documentation-supporting tooling changed only
* [ ] Code changes are intentionally included

## Testing

<!-- Documentation-only PRs may only require validation of commands/examples. -->

* [ ] Documentation reviewed
* [ ] Example commands verified
* [ ] No tests required

## Checklist

* [ ] No secrets or credentials included
* [ ] No unrelated changes included
* [ ] Documentation matches the current repository
