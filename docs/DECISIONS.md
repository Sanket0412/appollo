# Appollo — Open Decisions

Questions raised by [BUILD_PLAN.md](./BUILD_PLAN.md) §9 that need Sanket's call. Add new ones here as they come up during the build rather than leaving them buried in chat.

| # | Question | Default if unanswered | Answer |
|---|---|---|---|
| 1 | Do IT consulting / offshore-delivery consultancies that file many LCAs count as staffing agencies to exclude? | Keep large product and consulting companies; exclude only names on the explicit staffing blocklist in `search.yaml` | **Keep large consulting and product companies; exclude only names on the staffing blocklist.** (2026-09-29) |
| 2 | Are the default title exclusions right, especially `lead` (currently allowed) and `manager` (currently excluded)? | Keep as specified in `search.yaml` | **Keep as-is: `manager` stays excluded, `lead` stays allowed.** (2026-09-29) |
| 3 | Is the email digest wanted? | Built as optional; only activates when `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` / `DIGEST_TO` are set | **Yes, build it.** Sanket will add a Gmail app password before Step 9. (2026-09-29) |

## How to resolve

Tell Claude Code your answer in conversation; it will update the "Answer" column here and adjust `config/search.yaml` or the relevant code if the default needs to change.
