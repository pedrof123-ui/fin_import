# review-phase

Use this command prompt to ask a reviewer agent to review a completed phase.

## Prompt template

```text
Read CLAUDE.md, ACTION_PLAN.md, AGENTIC_TEAM_FRAMEWORK.md, and REVIEWER_APPROVAL_CRITERIA.md.

Use the <quant-reviewer-agent or code-reviewer-agent>.

Review Phase <PHASE_NUMBER>: <PHASE_NAME>.

Review the implementation against REVIEWER_APPROVAL_CRITERIA.md.

Return exactly one decision:
- APPROVE
- REQUEST CHANGES
- BLOCK

End with the required Review Result format.
```
