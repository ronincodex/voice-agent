# Phase 7 — Frontend

## Objective

Build a Next.js dashboard and admin interface that talks to the
FastAPI backend over HTTP. Satisfies PDF Sections 7 (agent
configuration screen), 8 (call dashboard), 9 (recording playback),
and 19 (live-deployed application with a phone-number input).

By the end of the phase the deployed application at
https://voice-agent-ochre-two.vercel.app supports:

  - Dashboard home with live counters
  - Calls list with pagination and filters
  - Call detail with transcript, AI summary, and audio playback
  - Agent configuration form with live greeting preview
  - Call trigger page with phone number input
  - Per-language voice selection
  - Persona gender selection derived from the voice

## Commits

| Hash | Title |
|---|---|
| 5fd4fe9 | feat(api): enable CORS for the frontend origin |
| e276834 | chore(frontend): scaffold Next.js 16 + Tailwind v4 + shadcn/ui |
| 3eda257 | feat(frontend): sidebar layout and live stats dashboard |
| 317b5d9 | feat(frontend): URL state foundation for the calls page |
| debaa2f | feat(frontend): calls table with status and direction badges |
| d5f39d7 | feat(frontend): call filters and pagination via URL state |
| 4963562 | feat(frontend): call detail route — 404 and loading states |
| a814817 | feat(frontend): call metadata panel and audio player |
| 32d07dc | feat(frontend): call transcript and detail page |
| 0109429 | chore(frontend): install form primitives and mount Toaster |
| 98ce916 | feat(frontend): agent configuration form with live greeting preview |
| 7c7107b | feat(api): derive Vobiz callback URLs from PUBLIC_BASE_URL |
| b892927 | feat(api): PUBLIC_BASE_URL and envelope-wrapped /languages |
| 3d4fb3e | feat(frontend): call trigger page at /call/new |
| bddfe31 | feat(api): support multiple frontend origins for CORS |
| 638e0d8 | fix(frontend): add ngrok skip header to browser-side fetches |
| 5342418 | feat(frontend): per-language voice selection in agent config |
| 2b5dcae | fix(agents): persona gender must match voice selection |
| 6778412 | fix(frontend): persona gender field with voice-derived default |

## Phase 7.1 — Dashboard read endpoints

Three read-only endpoints in `server.py`:

  - GET /calls                 paginated, filterable list
  - GET /calls/stats           four counter values
  - GET /calls/{uuid}          full detail with transcript
  - GET /calls/{uuid}/recording-url  presigned R2 URL

New file `api/schemas.py` defines the response envelope
(`ApiResponse[T]`, `PaginatedResponse[T]`) and the domain models
(`CallSummary`, `CallDetail`, `TranscriptMessage`,
`RecordingUrl`, `CallStats`).

Design decisions:

  Offset pagination, not cursor. The dashboard needs arbitrary
  page navigation, which cursor pagination cannot support without
  a separate endpoint. Cursor pagination's performance advantage
  is irrelevant at this project's row counts.

  CallSummary is narrow on purpose. The list endpoint returns 11
  fields per row, not the full metrics and summary JSONB blobs.
  The detail endpoint fetches the rest.

  Routes ordered /calls/stats before /calls/{uuid} so FastAPI
  does not interpret 'stats' as a call_uuid.

  Fixed a pre-existing bug: the WebSocket handler was creating
  every call record with from_number='' and to_number=''. The
  query string now carries both. Historical rows from Phases 4-6
  remain empty; backfilling is out of scope.

## Phase 7.2 — Agent configuration backend

New `agent_configs` singleton table with `config_key TEXT PRIMARY
KEY` pinned to 'default' by a CHECK constraint. Typed columns for
the nine operator-editable fields; `voice_overrides JSONB` for
per-language TTS voice and STT locale keyed by BCP-47 code.

Endpoints:

  GET  /agents/config   returns the current row
  PUT  /agents/config   replaces it

PUT not POST because the body is a full replacement and PUT is
idempotent. Validation rejects unknown language codes, a
primary_language not in supported_languages, and voice_overrides
keys that are not supported languages. `AgentConfigPayload` uses
`extra='forbid'` so a typo in a field name is a 422 rather than
being silently dropped.

Runtime integration in `agent_pipeline.py`:

  - `_apply_config_overrides` merges agent_name, greeting_template
    (with {name} and {company} substituted), and a personality +
    objective addendum into the LanguageConfig.
  - `_apply_voice_overrides` applies per-language tts_voice,
    tts_language_code, stt_locale from the JSONB.
  - Compliance strings (consent_disclosure, guardrail_deflect,
    farewell) are deliberately NOT overridable from the UI.
  - A config load failure logs and proceeds with the in-code
    defaults. A config problem must never block a call.

Caching in `db/agent_config.py` uses a module-level variable with
a 60 s TTL. NOT `functools.lru_cache`, because decorating an
async function caches the coroutine, not the result.

Two bugs found during end-to-end verification:

  1. AgentConfig was missing `config_key` as a field, so the read
     path rejected every row with an extra_forbidden error.
  2. `_start_flow` used the base language config from
     `get_language_config()` rather than the overridden config
     that `create_agent_pipeline` stored in `flow_manager.state`.
     The pipeline applied the overrides correctly, but the
     greeting node was initialized with the base config. Caught
     by listening to a real call — the greeting said "Priya"
     after the config was set to "Aarav".

## Phase 7.3 — Frontend scaffold

Next.js 16.3.8 (App Router, TypeScript, Turbopack dev server),
Tailwind CSS v4, shadcn/ui with default settings, import alias
@/* -> ./*.

The initial `npm install` failed repeatedly from the home
network with ETIMEDOUT on `@next/swc-linux-x64-gnu` (~40 MB). The
network has a sustained-transfer problem — small packages
downloaded fine, only the large one dropped. Succeeded from a
mobile hotspot (359 packages in 31 s). npm cache is now warm.

Layout:

  - components/app-sidebar.tsx  Client Component, usePathname
  - components/stat-card.tsx    Server Component, pure presentation
  - app/layout.tsx              Root layout with sidebar + main
  - app/page.tsx                Server Component fetching /calls/stats

Added CORS middleware to the backend, restricted to
`settings.frontend_origin` (default http://localhost:3000).
Explicit origins and methods, not '*'. `allow_credentials=True`
with a wildcard origin is rejected by browsers.

## Phase 7.4 — Calls list page

Three parts.

Part 1 — URL state foundation:

  - `lib/search-params.ts` defines the URL schema with
    `createSearchParamsCache` for server-side parsing and parser
    objects for client-side hooks.
  - `NuqsAdapter` wraps the app in `app/layout.tsx`.
  - New `app/calls/page.tsx` placeholder.

Part 2 — the table:

  - `components/calls-table.tsx` TanStack Table v9 DataTable with
    eight columns. Three `manual*` flags tell the table that the
    server paginates, filters, and sorts.
  - `components/call-status-badge.tsx` and
    `components/call-direction-badge.tsx` for the Status and
    Direction columns.
  - `app/calls/loading.tsx` skeleton.

Part 3 — filters and pagination:

  - `components/calls-filters.tsx` direction and status dropdowns
    plus a Clear button.
  - `components/calls-pagination.tsx` Previous/Next with "Page X
    of Y" and "Showing N-M of Z".

**Critical fix during Phase 7.4:** nuqs defaults to
`shallow: true`, which updates the URL via `history.replaceState`
without triggering a Next.js navigation. The URL bar changed but
the Server Component never re-rendered, so the table showed stale
rows. Diagnosed by comparing nuqs `setPage` (URL changed, content
did not) against `router.push` (URL changed, content
re-rendered). Fix: `shallow: false` on the parsers in
`lib/search-params.ts`. This matches the nuqs recommendation of
configuring options on the parser itself, so a new component
inherits the option automatically.

**TanStack Table v9 migration:** npm installed v9.2.5, but the
plan assumed v8. v9 is an API rewrite:

  - `useReactTable` -> `useTable`
  - `getCoreRowModel()` no longer exists
  - `createColumnHelper<typeof features, TData>()`
  - `columns` wrapped in `columnHelper.columns([...])`
  - `<table.FlexRender cell={cell} />` replaces `flexRender(...)`
  - Explicit `tableFeatures({...})` registration required

Features registered: `columnFilteringFeature`,
`columnVisibilityFeature`, `rowPaginationFeature`,
`rowSortingFeature`. No row model factories registered — the
server does the actual pagination, filtering, and sorting.

`"use client"` added because `useTable` is a hook, and hooks
cannot run in a Server Component.

## Phase 7.5 — Call detail page

Three parts.

Part 1 — route scaffolding:

  - `app/calls/[call_uuid]/not-found.tsx`  route-specific 404
  - `app/calls/[call_uuid]/loading.tsx`    skeleton

Part 2 — metadata and audio:

  - `components/call-metadata.tsx` Server Component with three
    cards (direction, from/to, duration) plus the AI summary
    card when `calls.summary` is present.
  - `components/call-audio-player.tsx` Client Component. Fetches
    the presigned R2 URL lazily on first play so the URL is
    always fresh (presigned URLs expire after one hour). HTML5
    `<audio>` with a shadcn Slider for seeking.

Part 3 — transcript and page:

  - `components/call-transcript.tsx` chat-style transcript.
    User messages right-aligned with accent background,
    assistant left-aligned with muted. ScrollArea caps height
    at 600px.
  - `app/calls/[call_uuid]/page.tsx` Server Component. Awaits
    `params` (Promise in Next.js 16), fetches the call, calls
    `notFound()` on 404. `generateMetadata` returns a page title
    from direction and timestamp.

Playback position is transient React state, not URL state. The
opposite of the filters-and-pagination case where URL state is
correct.

**Base UI migration:** shadcn/ui moved from Radix to Base UI in
July 2026. Two API changes:

  - `Button` no longer accepts `asChild`. Links with button
    styling now use `buttonVariants` on a plain `<Link>`. Also
    preserves the anchor's semantic role — Base UI's Button
    applies `role='button'`, which breaks link affordances.
  - `Slider`'s `onValueChange` emits `number | readonly number[]`
    rather than `number[]`. Normalised with a typeof check rather
    than a cast.

## Phase 7.6 — Agent configuration form

Live at `/config`. Ten fields, RHF + Zod resolver, live greeting
preview.

  - `lib/agent-config-schema.ts` Zod schema mirroring the
    backend's `AgentConfigPayload`. Cross-field rules for
    primary_language and voice_overrides.
  - `app/config/loading.tsx` and `app/config/page.tsx`.
  - `components/agent-config-form.tsx` Client Component.
  - `components/greeting-preview.tsx` live preview that updates
    on every keystroke.

Design decisions:

  Save is disabled until `isDirty`. Prevents accidental empty
  PUTs.

  Discard re-fetches, does not reset to hardcoded defaults.

  On success: reset the form with the server's response, call
  `router.refresh()` so the Server Component re-fetches, show a
  toast.

  `useWatch` is used instead of `watch()` in the component body.
  `watch()` returns a function React Compiler cannot memoize,
  which disables memoization for the entire component.

**Zod 4 note:** Removed `.default()` from `company_info` and
`voice_overrides`. In Zod 4, `.default()` makes the input type
allow undefined while the output type is required. `zodResolver`
sees the input type, `useForm<T>` uses the output type, and the
mismatch breaks inference.

The form calls the API directly for the PUT because `fetchApi`
only handles GET. Reuses `ApiError` for consistent error
handling.

## Phase 7.7 — Call trigger page

`/call/new` route with a phone number input, language dropdown,
and Start Call button. Replaces the curl command with a button.

Backend gains `PUBLIC_BASE_URL`. When `/call` receives a request
without explicit `answer_url`, it derives `answer_url`,
`hangup_url`, and `ring_url` from `PUBLIC_BASE_URL`. Explicit
URLs in the request body still win, so the existing curl
workflow is unchanged.

Also fixed: `/languages` predated the Phase 7.1 envelope and
returned a raw dict. Frontend `fetchApi<T>` unwraps `body.data`,
so the response had no data field and threw. Wrapped in
`ApiResponse[dict]`. No other consumer existed.

## Phase 7.8 — Vercel deployment

Frontend deployed to Vercel. Root Directory set to `frontend/`.
Environment variable `NEXT_PUBLIC_API_BASE_URL` set to the ngrok
URL. Production alias: https://voice-agent-ochre-two.vercel.app

`FRONTEND_ORIGIN` (singular) became `FRONTEND_ORIGINS` (a
comma-separated list). Local development, the Vercel URL, and
future Vercel preview deployments can all be allowed at once.

**ngrok interstitial fix:** the deployed frontend could not fetch
the recording URL. The browser error was "No
Access-Control-Allow-Origin header is present" on a request to
the ngrok URL, which looked like a backend CORS bug. The backend
CORS was correct. The problem was ngrok's free-tier interstitial:
every browser request to `*.ngrok-free.dev` without
`ngrok-skip-browser-warning: true` receives an HTML warning page
instead of the API response. That warning page has no CORS
headers, so the browser blocked it. Server Component fetches
(dashboard, calls list, detail) run server-to-server on Vercel
and never see the interstitial, which is why those pages worked
while the audio player did not.

Fix: `BROWSER_HEADERS` exported from `lib/api.ts` includes the
skip header. Used by `fetchApi`, `fetchPaginated`, the config
form's PUT, and the call trigger's POST.

## Phase 7.9 — Voice selection

PDF Section 7 lists "Voice (including language/locale selection)"
as a configurable field. Backend supported it via the
`voice_overrides` JSONB, but no UI exposed it.

  - `lib/voice-options.ts` curates voice options per language,
    drawn from Sarvam Bulbul v3 documentation. Only recommended
    voices (Tier 1 and Tier 2 by Critical Error Rate) are
    surfaced.
  - `components/agent-config-form.tsx` gains a Voice Selection
    card. One dropdown per supported language. "Default" clears
    the override; a specific voice writes
    `{ tts_voice: '<id>' }` into `voice_overrides`. The section
    appears and disappears as languages are checked and
    unchecked.

No backend change — `_apply_voice_overrides` already reads the
JSONB and applies `tts_voice` to the TTS service.

## Phase 7.10 — Persona gender fix

Found during voice selection testing: changing the voice to a
male option made the TTS sound male, but the LLM continued to
write female first-person verb forms (`मैं समझती हूँ` instead of
`मैं समझता हूँ`).

Root cause: `_apply_config_overrides` overrode `persona_name`,
`greeting`, and `llm_prompt_suffix` from the config, but never
`persona_gender`. That field came only from `languages.py` and
was fixed per language.

Fix:

  - New `persona_gender` column on `agent_configs`, default
    'female', with a CHECK constraint limiting values to
    female / male / neutral.
  - `_apply_config_overrides` reads `persona_gender` and
    overrides `lang_config.persona_gender` when the value is
    valid.
  - Frontend gains a Persona gender Select below Agent name.
  - Selecting a voice auto-derives the persona gender from the
    voice's known gender, so the operator does not have to
    remember to change both. Manual override still works.

## Design Decisions

**URL state, not React state.** Filters, page number, and sort
order live in the URL. Refreshing preserves them; the URL is
shareable; the Server Component reads them directly without prop
drilling. React state would lose all of this on refresh.

**Server Components by default.** Every page fetches on the
server. Only the components that use hooks (`usePathname`,
`useTable`, `useQueryState`, `useState`) carry `"use client"`.
The rule of thumb: pure presentational -> Server; uses a hook ->
Client.

**Explicit CORS origins and methods.** Never `"*"`. The list
documents the API surface and the deployment topology in code.

**One config for one repo.** `pyproject.toml` at the root,
`package.json` inside `frontend/`. Two toolchains, one repo, no
collision.

## Validation

Every sub-phase has a browser checklist. The end-to-end
verification at Phase 7.10:

  - Changed agent name to "Maira" in the form
  - Preview updated on every keystroke
  - Toast: "Agent configuration saved"
  - Placed a call via the deployed frontend
  - Caller heard "Hello! I'm Maira calling from IT-Webhut..."
  - Transcript in the call detail page shows "Maira"
  - Reset to Priya, save, place another call
  - Greeting back to Priya
  - Changed Hindi voice to "Shubh — Confident & Bold"
  - Persona gender auto-switched to Male
  - Placed a call
  - Greeting sounded male
  - LLM wrote `मैं समझता हूँ` (male first-person)

## Known Gaps

Documented in `docs/compliance.md` and the phase dev-logs.
Summary of what Phase 7 did not address:

  - **Backend deployment.** The ngrok tunnel is temporary; the
    backend is still on the developer's laptop. Phase 8 moves it
    to Render.

  - **PlayedTextTracker placement.** Still receives zero
    TTSTextFrames because the output transport consumes them
    before our processor runs. Instrumented but not functional.
    Carried over from Phase 6.

  - **Mobile layout.** Sidebar is `hidden md:flex` — it does not
    render below 768px. A drawer menu is deferred.

  - **Full README.** The root README is a skeleton; the complete
    setup and deployment instructions are Phase 9.

  - **Cross-language voice parity.** The voice list has fewer
    options for Tamil and English than for Hindi. This reflects
    the Sarvam documentation's per-language recommendations,
    not a UI limitation.
