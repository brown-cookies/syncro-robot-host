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