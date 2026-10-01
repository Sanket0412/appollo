# Appollo

Appollo is Sanket Shah's personal job discovery pipeline. It finds fresh Data Scientist, ML Engineer and AI Engineer roles every day from public ATS APIs (plus light, local-only JobSpy searches), filters them, checks employer H-1B filing history against DOL LCA data, scores fit with Claude Haiku, and delivers a ranked list of apply links. Sanket applies to every job himself.

The full build spec lives in `docs/BUILD_PLAN.md`. Read it before starting any step.

## How to work in this repo

- Build one step of `docs/BUILD_PLAN.md` at a time. After each step, stop, tell Sanket exactly how to test it, and wait for his confirmation before starting the next step.
- Commit after each step passes, with a message like `step 4: ATS fetchers`.
- Before relying on any API endpoint, response field, library version, model name or price, verify it against current official docs or a live request. Tell Sanket what you verified and what you could not.
- Pin dependency versions in `requirements.txt` only after confirming they install and import cleanly.
- For large or hard-to-reverse changes (schema changes, new paid services, architecture changes), explain the tradeoff briefly and ask first. For small choices with an obvious default, pick it, say what you picked, and continue.
- Keep costs low. Prefer free tiers, the Message Batches API and caching. Call out anything that adds recurring cost.

## Environment

- Windows 11, PowerShell in the VS Code terminal. Repo path is `G:\Projects\Appollo\appollo`.
- Python 3.12 in `.venv`. Always run Python as `.\.venv\Scripts\python.exe` in scripts and scheduled tasks. Conda is also installed, so never assume the bare `python` resolves to the venv.
- The GitHub repo `Sanket0412/appollo` is PUBLIC. Anything committed and anything printed in GitHub Actions logs is visible to everyone.

## Hard rules (never break these)

1. Never build anything that automates Sanket's logged-in LinkedIn or Indeed account, including Easy Apply, messaging or connection requests.
2. Never auto-submit an application. Every submission is a human click.
3. Never bypass CAPTCHAs. Treat them as a stop point for Sanket.
4. Respect rate limits and cache results. Prefer official or public APIs over scraping.
5. Secrets live only in `.env` (gitignored) locally and in GitHub Secrets in CI. Never hardcode or commit keys, connection strings or passwords.
6. Personal data never goes into git or CI logs. This includes resume text, tracker contents, digests and job lists. Everything personal lives under `data/` (gitignored) or in Supabase. In CI, log counts only.
7. JobSpy runs only on Sanket's local machine. `pipeline/fetchers/jobspy_fetcher.py` must refuse to run when `GITHUB_ACTIONS=true`.
8. If outbound text generation is ever added (cover letters, emails, LinkedIn notes), it must never mention visa status, OPT, CPT, H-1B or sponsorship, and LinkedIn notes must be under 300 characters, both enforced in code. The current scope generates no outbound text.

## Tracker format (must not change)

The tracker columns are Company Name, Job Title, Years of Exp required, Sponsorship Status, Date of Application, One-line summary of the role. Sponsorship Status is exactly one of `Available`, `N/A`, `Not Mentioned`. The pipeline adds only two columns after these, i.e. `LCA filings (FY25 to FY26)` and `Relevant SOC filings`.

## Writing style for messages to Sanket

- Never use em dashes. Use commas, semicolons or hyphens.
- Never use colons in prose. Colons in code, config files and commands are fine.
- Be direct and concise. Give every code change as a complete file or a clearly located block, with the exact file path.

## Review console (filled in at Step 12)

When Sanket asks for today's jobs, query the `v_daily_digest` view through the Supabase MCP (read-only), show them grouped as NYC metro, Remote US, Elsewhere US, and include rank, company, title, YOE required, sponsorship status, LCA counts, one-line summary and apply link. To mark a job applied or skipped, run `.\.venv\Scripts\python.exe scripts/mark_applied.py <job_id_or_url>` (add `--skip` to skip).

If Sanket asks for help filling an application form with Claude in Chrome or Playwright MCP, fill fields only on the company's ATS page (never LinkedIn or Indeed), stop before the Submit button, stop at any CAPTCHA, and let Sanket review work-authorization and EEO answers and click Submit himself.