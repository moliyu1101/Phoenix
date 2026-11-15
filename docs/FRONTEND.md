# Phoenix frontend

The UI is a Chinese-localized Next.js command deck. Active views include Welcome,
ThreadRail, RunSignalsStrip, ActivityConsole/Waterfall/Ledger/Playback,
AgentCollaborationCanvas, SettingsNav, SettingsPage, SettingsSection,
AppearanceSettings and ShortcutsSettings. Knowledge, memory, evolution and
configuration views use the same settings primitives, table/list conventions,
palette and inspectors.

Native adapters are PhoenixNewChallenge, PhoenixSolve, PhoenixActivityTimeline,
PhoenixPageFrame, PhoenixPages, PhoenixConfiguration and PhoenixPreferences.
phoenixTrace maps persisted native events, tasks and model calls to TraceScenario;
only actual timing is displayed, and missing model prices/tokens remain unknown.
phoenixProjection maps workers, tasks and evidence handoffs into DeckState.

UI 3001 proxies authenticated requests to native API 18750. The workbench token is
stored in sessionStorage and passed in headers, never in URLs. Model credentials
remain on the server. Operator model/role/roster overrides and UI preferences are
durable files in the configured data directory; model secrets use a separate file
with mode 0600. Changes to model/roster settings are rejected while a live run is
nonterminal.

WorkspaceAppShell keeps a persistent activity rail across draft, run and management
routes, independent of ThreadRail collapse state, exposing the native workspaces plus
settings, theme and logout. Theme state follows the shared document theme.

Check with npm run typecheck, npm run check:phoenix, node scripts/check-trace.mjs,
npm run build and scripts/browser-check.mjs (real-browser acceptance suites).
See VALIDATION.md.