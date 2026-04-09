 

Use the existing technical core as the selling point and spend the limited 1-2 day budget on three things: sharpen the product story, remove prototype-like rough edges from the browser demo, and add lightweight evaluation evidence from the existing April data. This is the best impact-per-hour path for a live frontend demo aimed at showing product sense and NLP/ML engineering.

**Steps**

1. Phase 1 — tighten the story in the repo and demo entry points. Update the top of [README.md](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) so the first screen explains the user problem, who this is for at SRF, and why topic-centric navigation matters. Fix narrative inconsistencies such as 6x6 versus 7x7 and 14-day versus 7-day baseline so the story matches the actual implementation. This should happen before any polish work because it defines the framing for the rest.
2. Phase 1 — add a concise business framing section to [README.md](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) and optionally create PROPOSAL.md. Emphasize the product thesis, intended audience, why this matters for archive discovery, and what success would look like. Keep it short and concrete rather than speculative. This can run in parallel with step 1 if handled separately.
3. Phase 2 — improve live-demo trust signals in [app.js](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) and [index.html](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html). Add visible data freshness and snapshot context in the header or footer, add loading and fetch-error states for day changes, and make the About link open a short explanation of the method. These are low-effort changes that make the demo feel deliberate and production-aware.
4. Phase 2 — fix the most visible UX credibility issues in [style.css](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) and [app.js](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html). Raise the default readability of the word list, make missing-image cases explicit rather than silent, and remove interaction behaviors that feel broken when data is incomplete. This depends on step 3 only if the UI text/layout changes need to be coordinated.
5. Phase 3 — create a lightweight evaluation artifact from existing demo-data outputs. Add EVALUATION.md with simple, defensible metrics that can be gathered from current JSON/cache outputs: number of processed programs, average candidates, LLM pass rate, image/frame coverage, and a short manual quality spot-check. Avoid heavy experiments; use what is already available.
6. Phase 3 — surface one or two evaluation numbers inside the demo or [README.md](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html). For example: processed programs count, topics surfaced, image coverage, or filtering funnel. This can run in parallel with step 5 once the metrics are known.
7. Phase 4 — harden only the most visible backend/demo failure points in [pipeline.py](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html). Replace silent failures with contextual logging, improve quote extraction boundaries if obviously weak in the sample output, and validate output completeness before serving demo JSON. This is a secondary priority because it is less visible than story and demo polish.
8. Phase 5 — rehearse the live demo flow. Prepare a 2-3 minute narrative that starts with the user problem, shows one day in the grid, opens a topic with quotes and source links, then closes with how the ranking is generated and why this is useful for SRF. This depends on phases 1-3 being complete.

**Relevant files**

- [README.md](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) — primary narrative surface; currently undersells business value and contains mismatches with implementation details.
- [DECISIONS.md](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) — source for methodology context and project decisions; useful for extracting a short English summary and known tradeoffs.
- [index.html](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) — entry-point structure for About, subtitle, footer trust signals, and any lightweight presentation affordances.
- [app.js](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) — day loading, footer date logic, error/loading states, metadata display, and interaction polish.
- [style.css](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) — readability, missing-image treatment, and subtle polish needed for a live browser demo.
- [pipeline.py](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) — implementation truth for baseline window, grid size, quote extraction, and logging/error handling.
- [days.json](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) — drives available snapshots; useful for data freshness presentation.
- [all_scored_apr1.json](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) — likely source for lightweight metric extraction if the data is usable.
- [zeitgeist_20260401.json](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) — sample output for validating what the hiring team will actually see.

**Verification**

1. Cross-check README claims against [pipeline.py](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) constants and [app.js](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) behavior so the visible story matches the actual implementation.
2. Run the frontend locally and verify day switching, loading/failure states, footer/header context, About explanation, and incomplete-image handling using the existing demo-data snapshots.
3. Manually inspect one or two sample zeitgeist JSON files and confirm the surfaced evaluation numbers are true and easy to defend in conversation.
4. Spot-check at least 10 displayed topics for quote quality and image presence so the live demo does not accidentally open on weak examples.
5. Rehearse a short demo script and confirm it communicates both product sense and technical judgment within a few minutes.

**Decisions**

- Included scope: presentation, credibility, lightweight evaluation, and the most visible UX/backend trust issues.
- Excluded scope: new models, live production ingestion, larger redesigns, hourly pipeline work, extensive benchmarking, or infrastructure deployment work.
- Recommendation: prioritize changes that are visible in the first 60 seconds of a live browser demo and in the first screen of [README.md](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html).
- Recommendation: do not spend the limited budget on algorithmic improvements unless a visible output quality problem appears during manual spot checks.

**Further Considerations**

1. If there is time for only one deliverable, choose README plus frontend polish over backend improvements because the hiring team will experience those directly.
2. If the audience skews more product than engineering, add a short comparison against the current show-centric archive and one concrete user journey.
3. If the audience skews more technical, add a simple filtering funnel diagram or one table showing extraction to ranked output counts per day.

If you want, I can next turn this into a tighter one-page action checklist in Markdown for the next 2 days.