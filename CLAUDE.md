## Coding Standards

1. Use latest versions of libraries and idiomatic approaches as of today
2. Keep it simple - NEVER over-engineer, ALWAYS simplify, NO unnecessary defensive programming. No extra features - focus on simplicity.
3. Only manage exceptions when necessary.
4. Be concise. Keep README minimal. IMPORTANT: no emojis ever
5. Use uv; ALWAYS 'uv run xxx' NEVER 'python3 xxx'

6.  Whenever fixing a code bug, make sure that the code fix is generic and applicable to all stocks

7. THE ALPHA VANTAGE API HAS A LIMITS OF 75 CALLS/MINUTE. MAKE SURE THAT API CALLS DON"T EXCEED 75 CALLS/MINUTE

8. When implementing a plan, mark all phases and steps Complete in that plan's own file
   (root `PLAN_*.md` or `features/*/PLAN*.md`). Completed plans are moved to `archive/`.