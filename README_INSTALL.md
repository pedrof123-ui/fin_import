# Claude Code Agentic Team Installation

This bundle contains the markdown files needed to run a review-gated Claude Code agentic workflow for the fundamentals-alpha stock-selection project.

## Files included

```text
CLAUDE.md
ACTION_PLAN.md
AGENTIC_TEAM_FRAMEWORK.md
REVIEWER_APPROVAL_CRITERIA.md
README_INSTALL.md
.claude/agents/*.md
.claude/commands/*.md
```

## Where to place the files

Copy everything into the root of your existing Python quant project:

```text
your_existing_repo/
├── CLAUDE.md
├── ACTION_PLAN.md
├── AGENTIC_TEAM_FRAMEWORK.md
├── REVIEWER_APPROVAL_CRITERIA.md
├── README_INSTALL.md
└── .claude/
    ├── agents/
    └── commands/
```

Do not create a new project structure. These files are guidance/configuration for Claude Code.

## First Claude Code prompt

After copying the files, open Claude Code in the repo root and run:

```text
Read CLAUDE.md, ACTION_PLAN.md, AGENTIC_TEAM_FRAMEWORK.md, and REVIEWER_APPROVAL_CRITERIA.md.

Use the orchestrator agent.

Start with Phase 0 only:
1. Inspect the existing repository.
2. Identify current data, feature, model, notebook, test, and config structure.
3. Identify where the fundamentals-alpha action plan should be implemented.
4. Produce an integration map.
5. Do not modify production code.

End with the required Agent Result format and indicate whether review is needed.
```

## Important workflow rule

Do not ask Claude Code to implement all phases at once.

Use this sequence:

```text
Phase 0 -> Review -> Phase 1 -> Review -> Phase 2 -> Review -> ...
```

The critical hard gates are:

```text
Phase 1: Point-in-time validation
Phase 6: True monthly portfolio backtest
Phase 8: Live scoring pipeline
```
