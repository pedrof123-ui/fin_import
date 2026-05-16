# implement-phase

Use this command prompt to ask Claude Code to implement a specific phase.

## Prompt template

```text
Read CLAUDE.md, ACTION_PLAN.md, AGENTIC_TEAM_FRAMEWORK.md, and REVIEWER_APPROVAL_CRITERIA.md.

Use the orchestrator agent.

Implement Phase <PHASE_NUMBER>: <PHASE_NAME> only.

Rules:
- Do not implement later phases.
- Reuse the existing project structure.
- Follow the phase acceptance criteria in ACTION_PLAN.md.
- If the phase requires review, stop after implementation and request the required reviewer.
- End with the required Agent Result format.

Phase-specific instruction:
<ADD_SPECIFIC_INSTRUCTION_HERE>
```
