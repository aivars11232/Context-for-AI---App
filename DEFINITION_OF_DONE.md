# Context for AI — Definition of Done

A task or feature is complete only when all applicable conditions are satisfied.

## Implementation

- The requested behavior is implemented within the approved architecture.
- No unrelated behavior or future-scope feature was added.
- No empty placeholder is represented as complete.
- Dependencies flow in the approved direction.

## Verification

- Relevant unit tests pass.
- Relevant integration or behavioral tests pass.
- Existing tests still pass.
- Imports and static syntax checks pass.
- Application startup is verified when the task affects startup.

## Data and failure behavior

- Persistence changes have a migration or initialization path.
- Existing data is not destructively replaced.
- Errors are explicit and typed.
- Retry behavior is bounded.

## Documentation

- Requirements and component contracts remain accurate.
- Configuration changes are documented.
- The backlog and roadmap reflect actual status.

## Evidence

The completion report includes:

1. Files changed.
2. Commands executed.
3. Test and validation results.
4. Known limitations.
5. Confirmation that exit criteria passed.

If any condition is not met, the task status is not `Done`.
