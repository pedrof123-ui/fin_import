## Coding Standards

1. Use latest versions of libraries and idiomatic approaches as of today
2. Keep it simple - NEVER over-engineer, ALWAYS simplify, NO unnecessary defensive programming. No extra features - focus on simplicity.
3. Only manage exceptions when necessary.
4. Be concise. Keep README minimal. IMPORTANT: no emojis ever
5. Use uv; ALWAYS 'uv run xxx' NEVER 'python3 xxx'

6.  Except to XBRL mappings that are company specific, when fixing a code bug make sure that the code fix is generic and applicable to all stocks

7. THE ALPHA VANTAGE API HAS A LIMITS OF 75 CALLS/MINUTE. MAKE SURE THAT API CALLS DON"T EXCEED 75 CALLS/MINUTE

# CLAUDE.md

This is an existing Python quant finance project. The current objective is to improve and productionize a fundamentals-alpha stock-selection model.

Claude Code must follow a review-gated workflow. Do not create a new project structure.

## Required context files

Before making changes, read:

```text
ACTION_PLAN.md
AGENTIC_TEAM_FRAMEWORK.md
REVIEWER_APPROVAL_CRITERIA.md
```

## Project goal

Build a robust, point-in-time, investable, and explainable stock-selection pipeline based on company fundamentals.

The system should support:

- point-in-time fundamentals
- investable universe filters
- liquidity filters
- feature engineering
- XGBoost model training
- walk-forward validation
- baseline factor comparison
- true monthly portfolio backtesting
- risk diagnostics
- live scoring
- review-gated approval

## Core rules

1. This is an existing project. Inspect the current structure first.
2. Do not create a new parallel project.
3. Do not move files unless explicitly approved.
4. Reuse existing data, database, feature, model, and test utilities.
5. Implement one phase at a time.
6. Stop at review gates.
7. Reviewer agents must read `REVIEWER_APPROVAL_CRITERIA.md`.
8. No phase requiring approval may proceed without explicit `APPROVE`.
9. Do not present in-sample metrics as final evidence.
10. Do not use random train/test splits for final stock-return validation.
11. Do not use future fundamentals or future prices in features.
12. Do not treat overlapping forward returns as a tradable equity curve.
13. Do not hard-code credentials.
14. Do not hide failing tests.

## Required agent output format

Every implementation agent must end with:

```markdown
## Agent Result

### What changed
-

### Files modified
-

### Tests run
-

### Tests not run and why
-

### Review needed
Yes/No

### Reviewer requested
Quant Reviewer / Code Reviewer / Both / None

### Remaining risks
-

### Next recommended step
-
```

Every reviewer agent must end with:

```markdown
## Review Result

### Decision
APPROVE / REQUEST CHANGES / BLOCK

### Severity
blocker / major / minor

### Phase reviewed
-

### Files reviewed
-

### Evidence reviewed
-

### Findings
-

### Required fixes
-

### Optional improvements
-

### Can the next phase proceed?
Yes/No
```

## Reviewer approval criteria

Reviewer agents must read:

```text
REVIEWER_APPROVAL_CRITERIA.md
```

Reviewer agents must return one of:

```text
APPROVE
REQUEST CHANGES
BLOCK
```

No phase with `Approval required before next phase: Yes` may proceed without explicit approval from the required reviewer.

## First task

Start with Phase 0 only.

Use the orchestrator agent to inspect the repository and create an integration map. Do not modify production code in Phase 0.