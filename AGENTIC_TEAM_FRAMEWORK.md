# AGENTIC_TEAM_FRAMEWORK.md
## Claude Code Agentic Team for Fundamentals Alpha

This framework defines how Claude Code agents should implement the fundamentals-alpha action plan.

---

## 1. Team principle

Use a review-gated team, not a free-running coding swarm.

Builder agents implement. Reviewer agents approve, request changes, or block. A builder agent should not approve its own work.

---

## 2. Required files

Claude Code must read:

```text
CLAUDE.md
ACTION_PLAN.md
AGENTIC_TEAM_FRAMEWORK.md
REVIEWER_APPROVAL_CRITERIA.md
```

---

## 3. Agents

Create these project-level subagents under:

```text
.claude/agents/
```

Recommended agents:

```text
orchestrator.md
quant-research-agent.md
data-engineering-agent.md
feature-engineering-agent.md
ml-engineering-agent.md
backtest-engineering-agent.md
risk-portfolio-agent.md
qa-testing-agent.md
quant-reviewer-agent.md
code-reviewer-agent.md
documentation-agent.md
```

---

## 4. Agent responsibilities

### Orchestrator Agent

Owns task sequencing, scope control, and review gates.

### Quant Research Agent

Owns financial logic, factor definitions, benchmark logic, and economic interpretation.

### Data Engineering Agent

Owns data correctness, point-in-time alignment, filing-date logic, and data-quality checks.

### Feature Engineering Agent

Owns feature formulas, feature tests, missing-value handling, and sector-relative versions.

### ML Engineering Agent

Owns training, walk-forward validation, model diagnostics, SHAP, and live scoring.

### Backtest Engineering Agent

Owns true monthly portfolio simulation, turnover, transaction costs, and benchmark comparison.

### Risk & Portfolio Agent

Owns universe filters, liquidity, sector exposure, drawdown, beta, concentration, and guardrails.

### QA & Testing Agent

Owns unit tests, integration tests, regression tests, reproducibility, and test execution.

### Quant Reviewer Agent

Reviews methodology and can approve, request changes, or block.

### Code Reviewer Agent

Reviews code quality and can approve, request changes, or block.

### Documentation Agent

Owns README, runbook, assumptions, limitations, and user-facing instructions.

---

## 5. Phase workflow

Use this sequence:

```text
Phase 0: Repository Discovery
Phase 1: Point-in-Time Data Audit
Phase 2: Universe and Liquidity Filters
Phase 3: Feature Engineering Improvements
Phase 4: Baseline Factor Models
Phase 5: Walk-Forward Model Validation
Phase 6: True Monthly Portfolio Backtest
Phase 7: Risk Diagnostics and Guardrails
Phase 8: Live Scoring Pipeline
Phase 9: Documentation and Runbook
```

Each phase must end with the standard `Agent Result`.

A phase with review required cannot proceed until the required reviewer returns:

```text
Decision: APPROVE
```

---

## 6. Reviewer approval criteria

Detailed reviewer approval criteria are maintained in:

```text
REVIEWER_APPROVAL_CRITERIA.md
```

All reviewer agents must read that file before approving, rejecting, or blocking a phase.

---

## 7. Approval matrix

| Phase | Reviewer | Approval required before next phase? |
|---|---|---:|
| Phase 0: Repository Discovery | Code Reviewer | Yes |
| Phase 1: Point-in-Time Audit | Quant Reviewer | Yes |
| Phase 2: Universe/Liquidity Filters | Quant Reviewer | Yes |
| Phase 3: Feature Engineering | Code + Quant Reviewer | Yes |
| Phase 4: Baseline Factors | Quant Reviewer | Yes |
| Phase 5: Walk-Forward ML | Quant Reviewer | Yes |
| Phase 6: Monthly Portfolio Backtest | Quant Reviewer | Yes |
| Phase 7: Risk Diagnostics | Quant Reviewer | Yes |
| Phase 8: Live Scoring | Code + Quant Reviewer | Yes |
| Phase 9: Documentation | Code Reviewer | No, unless methodology changed |

---

## 8. Blocker issues

Any of these must stop the workflow:

```text
look-ahead bias
target leakage
future fundamentals in features
future prices in features
random split used for final validation
overlapping forward returns used as tradable equity curve
missing liquidity filters in investable backtest
benchmark date mismatch
transaction costs ignored
market-cap filters bypassed
hard-coded credentials
failing core tests
duplicate project structure
```

---

## 9. Standard implementation output

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

---

## 10. Standard review output

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

---

## 11. First Claude Code prompt

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
