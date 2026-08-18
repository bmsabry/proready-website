# RESTORE.md — Pick-up-where-you-left-off snapshot

**Purpose:** This file lives in the git repo so that if Cowork dies, your laptop dies, or a new agent starts cold, the project can be reconstructed without re-discovering every architectural decision. Update it whenever something non-obvious lands.

**Last updated:** 2026-05-06 (commit reflecting RESTORE.md creation; check `git log -1 RESTORE.md` for actual)

---

## 1. What this project is

**ProReadyEngineer training website** — marketing site + paid-training registration + admin dashboard. Built around one paid course initially: **Gas Turbine Emissions Mapping**, 5-day cohort starting **May 16, 2026**, $1,000 Founding Cohort price, $3,000 regular.

| Layer | Tech | Where it runs |
|---|---|---|
| Frontend | Vite + React + TypeScript + Tailwind | Cloudflare Pages (auto-deploys from `main`) |
| Backend | FastAPI + SQLAlchemy + Postgres | Render Web Service `proreadyengineer-training-api` (auto-deploys from `main`; the old `feature/registration-backend` branch is stale) |
| Email | Resend, sender `info@mail.proreadyengineer.com` | DKIM+SPF on Cloudflare DNS |
| Repo | https://github.com/bmsabry/proready-website | branches: `main` (prod), `feature/registration-backend` (Render deploy), `preview/gas-turbine-emissions-mapping` (Cloudflare Pages preview, currently disabled in dashboard) |

**Production URLs**
- Public: https://proreadyengineer.com
- Training detail: https://proreadyengineer.com/training/gas-turbine-emissions-mapping
- Admin: https://proreadyengineer.com/admin/login (email + password, httpOnly cookie session)
- Backend API: https://proreadyengineer-training-api-jd9a.onrender.com

---

## 2. Critical environment variables

### Render (`proreadyengineer-training-api`, service ID `srv-d7ip5i7avr4c73fs390g`)

The 17 env vars below MUST be present. Losing any of the bolded ones causes data loss or app crash.

| Key | Notes |
|---|---|
| **`AI_SETTINGS_KEY`** | Fernet master key encrypting the LLM API key in `ai_settings`. Format: 32-byte url-safe base64. **If lost, the stored API key becomes unreadable** — admin re-enters in `/admin → AI Settings`. Generate a new one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| **`DATABASE_URL`** | Auto-set by Render Postgres binding |
| **`ADMIN_PASSWORD_HASH`** | bcrypt hash of admin password |
| **`ADMIN_EMAIL`** | bmsabry@gmail.com — must match login form |
| **`SESSION_SECRET`** | 32+ char random string for itsdangerous cookie signing |
| `ADMIN_TOKEN` | Legacy token-auth for non-cookie admin calls; still wired |
| `RESEND_API_KEY` | re_…; for outbound email |
| `EMAIL_FROM` | `ProReadyEngineer <info@mail.proreadyengineer.com>` |
| `EMAIL_REPLY_TO` | `info@proreadyengineer.com` |
| `ADMIN_NOTIFY_EMAIL` | bmsabry@gmail.com — gets new-registration alerts |
| `CORS_ORIGINS` | `https://proreadyengineer.com` |
| `COURSE_CODE` | `gas-turbine-emissions-mapping-2026-05` |
| `COURSE_CAPACITY` | `15` (default; Course.total_seats overrides per row) |
| `COHORT_LABEL` | `May 15, 2026` (display only — Course.start_date is source of truth) |
| `COURSE_PRICE_DISPLAY` | (empty — frontend now shows the $1,000 price) |
| `PAYMENT_INSTRUCTIONS` | text shown in admin invoice email |
| `PYTHON_VERSION` | `3.11.9` |

### Cloudflare Pages

- `VITE_API_BASE` = `https://proreadyengineer-training-api-jd9a.onrender.com` — set in the Pages project settings.

### Where the actual secret values live

- `secrets.env` in your Google Drive (the project-handoff folder). Search for "RENDER_API_KEY" or browse `1tUr6jqDiyC90Hfuk3_D_DTjkJ3EY6tY6` parent.
- LLM API keys are in Google Drive too: `Agent Zero Settings.txt`. Includes Gemini, Anthropic, OpenAI, OpenRouter, etc.

---

## 3. Backend data model (high-level)

Three operational tables + four AI-assistant tables, all in Postgres on Render.

| Table | Purpose | Notes |
|---|---|---|
| `courses` | One row per cohort | Has `day_dates` JSON column added 2026-04-24 — admin-editable list of ISO dates per day; length = cohort length |
| `registrations` | One row per signup | `status` ∈ `pending` \| `paid` \| `cancelled`. **Public seat counter = paid + pending (active).** Capacity check uses active. mark_paid/cancel guards use paid. |
| `ai_settings` | Single row, LLM creds | `api_key_encrypted` is Fernet-encrypted with `AI_SETTINGS_KEY` |
| `ai_audit` | Tool-call + chat-turn log | One row per tool call / LLM turn / cap rejection |
| `ai_pending_actions` | Confirmation-pending tool calls | TTL 10 min. Snapshot includes full convo state to resume on Approve. |
| `ai_usage_daily` | Per-UTC-date token rollup | Drives the $5/day spend cap |

Migrations are idempotent and run on startup (`backend/app/main.py:_ensure_day_dates_column`). New tables auto-created via `Base.metadata.create_all`.

---

## 4. Feature inventory (what's been shipped)

Most-recent-first. Use `git log --oneline` for the full list — these are the load-bearing ones:

| Commit | Feature |
|---|---|
| `bb36485` | Hero infographic v8 (current image) |
| `82aa0ca` | A11y: bumped body text from slate-500 → slate-400 across the training page |
| `0397649` | Pricing copy adjustments per attached writeup |
| `5891259` | Reordered Pricing cards: simulator → Bassam → Q&A → examples → materials |
| `3d8ad91` | Added Founding Cohort Pricing section ($1,000 vs $3,000) |
| `e40b75c` | Removed the 6-circuits / dynamics-corridor flyer (CIRCUITS const dropped too) |
| `226f8c2` | Daily schedule section (4 time zones + hour-by-hour ET ruler) |
| `817693a` | Expanded Bassam bio + Testimonials link |
| `57ff1ba` | **AI assistant slice 2** — tool-calling, audit, $5/day cap, confirmations |
| `1920d92` | AI assistant slice 1 — settings + chat proxy |
| `ced8c2b` | Seat counter switched to active = paid + pending |
| `300a95f` | `day_dates` column + admin per-day editor |
| `fa22c06` | Live seats on listing card; static per-day dates on detail page |
| `2628df5` / `724f2fc` | Hero infographic v5/v4 swaps |
| `cfc75e4` | Admin pages get `pt-28` to clear the fixed navbar |

### What's pending (not built)

- **AI assistant slice 3:** public visitor chatbot widget with $5/day spend cap + per-IP rate limit. Plan: read-only system prompt scoped to course info; backend proxy at `/api/ai/visitor-chat`; frontend widget on every public page. Won't share the admin's `ai_settings` row directly — should have its own narrower scope.

---

## 5. AI assistant — quick reference

**Where:** `/admin → AI Settings` (configure LLM credentials), floating "Ask the assistant" button on every `/admin` page (chat).

**Tested provider:** Google Gemini via OpenAI-compat endpoint
- API URL: `https://generativelanguage.googleapis.com/v1beta/openai`
- Model: `gemini-2.5-flash-lite` (or `gemini-2.0-flash`, `gemini-2.5-pro`)
- Key from Google AI Studio

**Tools the agent can use:** `list_courses`, `get_course`, `update_course`, `list_registrations`, `mark_paid`, `cancel`, `bulk_mark_paid`, `bulk_cancel`, `notify_course`. Defined in `backend/app/ai_tools.py` — to add a tool, add a handler + register in `TOOL_HANDLERS` and `TOOL_SPECS`. High-stakes (always-confirm) list is in same file.

**Confirmation rule:** any `notify_course` AND any bulk op with ≥3 ids pause for admin Approve. Approve POSTs to `/api/admin/ai/actions/{id}/approve`; backend resumes the loop with the tool result fed in.

**Spend cap:** $5/day, tracked in `ai_usage_daily`, conservative pricing in `backend/app/ai_pricing.py` ($0.50/M input, $1.50/M output). Trips a 429 with reset-at-UTC-midnight message.

---

## 6. Cowork-only state (NOT in git, can be lost)

### Auto-memory entries

The `~/.auto-memory/` directory in Cowork holds context that future agents read. If Cowork dies, this is gone unless restored. Full contents are inlined below in section 9. Memory list:

- `MEMORY.md` — index
- `feedback_drive_large_download_workaround.md` — for big PNGs, jq+base64-d to disk
- `feedback_google_drive_default.md` — search Drive before asking user to upload
- `feedback_persistent_tunnel_pattern.md` — short-lived tunnels only; no watchdog promises
- `feedback_tunneling_tool.md` — cloudflared (not localtunnel)
- `project_admin_dashboard_live.md` — /admin login flow
- `project_admin_day_schedule.md` — `day_dates` semantics
- `project_ai_assistant_slice2.md` — tool-calling + audit + spend cap arch
- `project_backend_v1_scope.md` — async-invoice payment, no SignWell/Stripe
- `project_course_management_shipped.md` — admin course CRUD
- `project_email_sender_mail_subdomain.md` — Resend setup
- `project_render_deploy_live.md` — auto-deploy + psycopg3 gotcha
- `project_seat_count_active.md` — paid+pending semantics
- `reference_backup_skill.md` — (this file references that one; the original is now superseded by THIS file)
- `reference_render_and_secrets.md` — Drive → secrets pointer

### Scheduled tasks

| Task | State | Purpose |
|---|---|---|
| `proready-tunnel-keepalive` | **DISABLED** | Was attempting to keep cloudflared tunnel alive; abandoned because Cowork sandbox tear-downs kill detached processes too aggressively. Re-enable only if a fundamentally different approach lands. |
| `linkedin-day1-live-may4` … `linkedin-day6-live-may15` | (set up by user) | Self-notifications for each LinkedIn post in the launch campaign. **Preserve these.** Created by Bassam, not by me — don't touch. |

---

## 7. Local development

```bash
# Clone
git clone https://github.com/bmsabry/proready-website.git
cd proready-website

# Frontend
npm install
echo "VITE_API_BASE=https://proreadyengineer-training-api-jd9a.onrender.com" > .env.local
npm run dev   # http://localhost:5173

# Backend (separate shell)
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Set env vars (see section 2). For local dev, DATABASE_URL=sqlite:////tmp/proready.db works.
export AI_SETTINGS_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export ADMIN_EMAIL=admin@local
export ADMIN_PASSWORD_HASH=$(python3 -c "import bcrypt; print(bcrypt.hashpw(b'localdev', bcrypt.gensalt()).decode())")
export SESSION_SECRET=local-dev-secret
export EMAIL_FROM=local@example.com  RESEND_API_KEY=x  ADMIN_NOTIFY_EMAIL=local@example.com
uvicorn app.main:app --reload --port 8000
```

---

## 8. Recovery scenarios

### If Render service is gone

1. Create a new Web Service from the GitHub repo, branch `feature/registration-backend`, build command `pip install -r requirements.txt`, start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
2. Attach a Render Postgres add-on, copy `DATABASE_URL` into env.
3. Set ALL env vars from section 2 (especially `AI_SETTINGS_KEY` — generate a NEW one, then re-enter the LLM API key in `/admin → AI Settings`).
4. Update Cloudflare Pages `VITE_API_BASE` to the new Render URL.
5. Update `CORS_ORIGINS` on Render if frontend domain changed.

### If Cloudflare Pages is gone

1. New project pointing at the same GitHub repo, build command `npm run build`, output `dist`, branch `main`.
2. Set `VITE_API_BASE` env var to the Render URL.
3. Reconnect custom domain `proreadyengineer.com`.

### If the LLM API key is leaked

1. Revoke it at the provider (Google AI Studio, etc.).
2. Generate a new key.
3. Sign in at `/admin → AI Settings`, paste new key, save.
4. The encrypted blob in `ai_settings` is replaced.

### If `AI_SETTINGS_KEY` rotates

The stored encrypted API key becomes garbage. The `decrypt()` helper raises `CryptoNotConfigured` with a message telling the admin to re-enter. Just sign in to `/admin → AI Settings` and paste the LLM API key again.

---

## 9. Auto-memory dump (verbatim copy as of restore-file creation)

The full contents of `~/.auto-memory/` are below so a new agent can recreate them. Each block is a separate file; copy each into `~/.auto-memory/<filename>.md`.

> **Note:** these may be slightly out of date by the time you read this. Check `git log RESTORE.md` to see when this dump was written, and prefer current code/DB over these notes if they conflict.

```
===== MEMORY.md =====
- [Default to Google Drive for project reference files](feedback_google_drive_default.md) — in Cowork, search Drive for referenced handover/instruction/secret files before asking the user to upload
- [ProReadyEngineer Render account + secrets in Drive](reference_render_and_secrets.md) — Render API key, GitHub PAT, Stripe, PayPal, Resend, SignWell etc. live in Drive; marketing site and marketplace are separate projects
- [Use cloudflared for preview tunnels, not localtunnel](feedback_tunneling_tool.md) — ProReadyEngineer site requires `*.trycloudflare.com` tunnels; install cloudflared binary rather than substituting localtunnel
- [Persistent cloudflared tunnel pattern](feedback_persistent_tunnel_pattern.md) — Cowork sandbox tears down per Bash call; persistent preview needs scheduled-task heartbeat (every min) + setsid nohup detachment + node-direct vite launch (not npm run dev which exits 144)
- [ProReadyEngineer Website backup procedure](reference_backup_skill.md) — when Bassam says "back up" etc., read and follow BACKUP_SKILL.md at workspace root; overwrites INSTRUCTIONS + tarballs
- [ProReadyEngineer training-API v1 scope](project_backend_v1_scope.md) — Phase 2 backend is FastAPI + Postgres with async-invoice payment; NO SignWell, NO inline Stripe — don't add them back
- [ProReadyEngineer training-API is deployed on Render](project_render_deploy_live.md) — live URL, admin token, Auto-Deploy from feature/registration-backend, psycopg3 gotcha
- [ProReadyEngineer admin dashboard is live](project_admin_dashboard_live.md) — /admin/login email+password flow; rotate via ADMIN_PASSWORD_HASH + SESSION_SECRET env vars on Render
- [Email sender is info@mail.proreadyengineer.com](project_email_sender_mail_subdomain.md) — Resend verified, DKIM+SPF on Cloudflare, EMAIL_FROM updated on Render to fix spam-folder delivery
- [Course management feature shipped](project_course_management_shipped.md) — admin can set/edit start date, seats, status; auto-emails registrants on date change; public page reads from DB
- [Admin-editable per-day course schedule](project_admin_day_schedule.md) — Course.day_dates JSON list is single source of truth for cohort length + per-day dates; admin manages via /admin → Courses; no auto-email on day_dates change
- [Public seat counter = active (paid + pending)](project_seat_count_active.md) — registration takes a seat on submission, not on mark-paid; CourseOut exposes both seats_taken (active) and seats_paid; capacity gate + MarkPaidOut.taken both use active
- [Admin AI assistant slice 2 shipped](project_ai_assistant_slice2.md) — tool-calling agent with audit log, $5/day cap, confirm-on-mass-actions; OpenAI-compat protocol; new tools added via TOOL_HANDLERS + TOOL_SPECS in ai_tools.py
- [Drive MCP write EOF workaround](feedback_drive_large_download_workaround.md) — for large binaries, skip download_file_content and curl drive.google.com/uc?export=download directly with cookie jar + confirm-token fallback

===== project_admin_dashboard_live.md =====
---
name: ProReadyEngineer admin dashboard is live
description: Email+password login at proreadyengineer.com/admin/login backed by signed cookie session against Render API. Auth env vars and routes documented for future maintenance.
type: project
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---
**Shipped 2026-04-20** — replaces the bearer-token-only admin flow.

**URLs:**
- Login: https://proreadyengineer.com/admin/login
- Dashboard: https://proreadyengineer.com/admin
- API base: https://proreadyengineer-training-api-jd9a.onrender.com
- Admin email: bmsabry@gmail.com (case-insensitive match against `ADMIN_EMAIL` on Render)

**Backend endpoints** (all under `/api/admin/`, defined in `backend/app/routes/auth.py` and `routes/admin.py`):
- `POST /login` — email + password → sets `admin_session` httpOnly Secure SameSite=none cookie (7 days)
- `POST /logout` — clears cookie
- `GET /me` — returns `{email}` if authenticated, else 401
- `GET /registrations`, `POST /mark-paid`, `POST /cancel` — accept either the session cookie OR an `Authorization: Bearer <ADMIN_TOKEN>` header

**Render env vars driving auth** (set 2026-04-20):
- `ADMIN_EMAIL=bmsabry@gmail.com`
- `ADMIN_PASSWORD_HASH` — bcrypt hash; rotate by replacing this var (no in-app rotation UI)
- `SESSION_SECRET` — itsdangerous serializer key; rotating it invalidates all sessions
- `SESSION_MAX_AGE_SECONDS=604800` (7 days, default)
- `ADMIN_TOKEN` — kept as escape hatch for curl/scripts
- `EMAIL_FROM` — also fixed in this deploy to `ProReadyEngineer <noreply@promechdirectory.com>` (verified Resend domain); `EMAIL_REPLY_TO` still points to info@proreadyengineer.com so replies land in his real inbox

**Why:** Bassam wanted to log in with email+password from the live site rather than passing a bearer token via curl. Mark-paid and cancel work directly from the dashboard now.

**How to apply:** To rotate the admin password, generate a new bcrypt hash:
```python
import bcrypt; print(bcrypt.hashpw(b"NEW_PW", bcrypt.gensalt()).decode())
```
Then PUT it as `ADMIN_PASSWORD_HASH` in Render env vars (same flow as before — the env-var update triggers a redeploy). To reset all sessions, regenerate `SESSION_SECRET` similarly.

**Cross-origin cookie note:** the cookie is `SameSite=None; Secure; HttpOnly` because frontend (`proreadyengineer.com`) and API (`onrender.com`) are different sites. CORS is `allow_credentials=True` with explicit allowed origins (`https://proreadyengineer.com`, `https://www.proreadyengineer.com`). Don't widen origins to `*` — that would break the cookie.

===== project_admin_day_schedule.md =====
---
name: Admin-editable per-day course schedule
description: Course.day_dates is the source of truth for cohort length and per-day dates; admins manage it in /admin → Courses
type: project
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---
Course model has a JSON column `day_dates` (list of ISO yyyy-mm-dd strings). The number of days in a cohort = `len(day_dates)`. There is no separate `duration_days` field.

**Why:** Admin needs to change individual day dates and adjust cohort length without code edits.

**How to apply:**
- Backend: `PATCH /api/admin/courses/{code}` accepts `day_dates: list[date]`, replaces wholesale. `day_dates` changes do NOT auto-email registrants (only `start_date` does).
- Migration: `_ensure_day_dates_column()` in backend/app/main.py runs an idempotent ALTER on startup; safe across redeploys.
- Public detail page (`GasTurbineEmissionsMapping.tsx`) renders `day_dates.length` cards, zipping topics from local CURRICULUM array. For days beyond CURRICULUM.length, a `TBD_DAY` placeholder is shown — adding a 6th/7th day works without code, but the curriculum content for that day will read "Schedule TBD" until topics are added in code.
- Listing card (`Training.tsx`) shows `${day_dates.length} Days` instead of hardcoded "5 Days" when API returns the list.
- Curriculum content (titles, summaries, topics, icons) lives in the per-course detail page file. To add a new course's content, create a new detail page; admin only manages dates/seats/status via the dashboard.

===== project_ai_assistant_slice2.md =====
---
name: ProReadyEngineer admin AI assistant — slice 2 shipped
description: Tool-calling agent in /admin with confirmation flow, audit log, and $5/day spend cap. OpenAI-compatible protocol; works with Gemini OpenAI-compat endpoint.
type: project
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---
**State:** slice 2 deployed 2026-04-27 (commit 57ff1ba). Slice 3 (public visitor widget with rate limit) still pending.

**Architecture:**
- Settings stored in `ai_settings` (encrypted with `AI_SETTINGS_KEY` Fernet env var on Render).
- Tool registry in `backend/app/ai_tools.py` — JSON-Schema specs + Python handlers. Adding a new tool = entry in `TOOL_HANDLERS` + `TOOL_SPECS`. High-stakes detection in `is_high_stakes()`.
- Tool-calling loop in `backend/app/routes/ai.py` `_run_loop()`. Uses standard OpenAI `tools` + `tool_calls` + tool-result protocol. Iteration cap = 8.
- High-stakes interception: any `notify_course` (always) and bulk_mark_paid/bulk_cancel ≥ 3 ids pause for admin Approve. Pending state stored in `ai_pending_actions` table with full conversation snapshot + 10-min TTL.
- Approve flow: `POST /api/admin/ai/actions/{id}/approve` re-loads snapshot, executes, audits, resumes loop. Deny flow tells the model "admin denied" so it can suggest alternatives.
- Audit log: `ai_audit` table captures every tool call (kind=tool), every LLM turn (kind=chat), and cap-rejected requests (kind=cap_hit). Visible in Activity log section under AI Settings tab.
- Spend cap: `ai_usage_daily` rolls up tokens per UTC date. Conservative pricing in `ai_pricing.py` ($0.50/M in, $1.50/M out). Cap = $5/day. Checked BEFORE each LLM call, trips 429.

**Frontend (`AdminDashboard.tsx`):**
- `AdminChatWidget` floating panel renders Approve/Deny buttons inline when message has `pending_action`. `actionsExecuted` chips show silently-run tools above the next assistant bubble.
- `AIActivitySection` renders audit table (last 100, refreshable, color-coded kinds, error rows tinted red).

**Frontend conversation state:**
- Frontend only sends/receives `{role: user|assistant, content}` messages. Tool calls and tool results live server-side in pending_action snapshot — frontend never sees them.
- On Approve, frontend POSTs to /actions/{id}/approve and gets back another `AIChatOut` (which may itself have a new pending_action — chained confirmations work).

**Tools available to the agent (`TOOL_HANDLERS`):** list_courses, get_course, update_course, list_registrations, mark_paid, cancel, bulk_mark_paid, bulk_cancel, notify_course.

**System prompt** (in `routes/ai.py`) tells the agent: course code conventions, ISO date format, day_dates wholesale-replace semantics, plain-text email body, confirmation behavior. Frontend system prompts are ignored (backend always overrides) so a malicious page can't tell the agent "ignore tools".

**How to add a new tool:** function in `ai_tools.py` taking `db: Session, **kwargs` returning `{"ok": bool, ...}`, register in `TOOL_HANDLERS` and `TOOL_SPECS`. Add to `HIGH_STAKES_ALWAYS` or `HIGH_STAKES_BULK_TOOLS` if it needs confirmation.

===== project_backend_v1_scope.md =====
---
name: ProReadyEngineer training-API v1 scope
description: The Phase 2 registration backend deliberately excludes SignWell and inline Stripe Checkout — don't add them back without being asked
type: project
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---
Phase 2 backend (`backend/` on proready-website repo, branch `feature/registration-backend`) was scoped intentionally small on 2026-04-19:

**In scope for v1:**
- FastAPI + Postgres on Render (free tier + free DB)
- POST /api/register: creates pending lead, Resend confirmation email, admin notification, honeypot, email-idempotency
- GET /api/seats: paid-only count (source of truth for remaining seats on the public site)
- Admin endpoints (bearer-token auth): list, mark-paid, cancel
- Payment happens async: Bassam manually sends a Stripe Payment Link or PayPal invoice after registration, then flips the row to `paid` via the admin endpoint — which decrements visible seats on the live site

**Deliberately excluded (don't reintroduce without asking):**
- **SignWell** — Bassam said "this is not needed at all here" when asked. E-signatures were in the old INSTRUCTIONS but got cut from v1.
- **Inline Stripe Checkout** — adds webhook plumbing for zero user-facing benefit given the cohort size (15 seats) and current async-invoice flow.
- **Alembic migrations** — single-table schema; `Base.metadata.create_all` on startup is enough. Add Alembic only if the schema grows.

**Why:** Scope was set to "smallest thing that replaces the manual email-my-form-data loop." Registration form → confirmation email → manual payment → admin mark-paid. Keep it that way.

**How to apply:** If a future conversation implies adding e-signatures, webhook-driven auto-payment, or multi-table schema changes, surface the existing v1 scope before building — those might be Phase 3, not Phase 2.

===== project_course_management_shipped.md =====
---
name: Course management feature shipped
description: ProReadyEngineer admin can manage any course (start date, seats, status) and broadcast to registrants; public training page pulls data from DB
type: project
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---
Course management feature is live on production (both Render backend and Cloudflare Pages frontend).

**What shipped:**
- `Course` table with `code` (PK), `title`, `start_date`, `total_seats`, `status` ("open"/"closed"). Seeded on startup with `gas-turbine-emissions-mapping-2026-05`.
- Public endpoint `GET /api/courses/{code}` returns title, start_date, total_seats, seats_taken, seats_remaining, status.
- Admin endpoints under `/api/admin/courses`: list, create, get, PATCH (title/start_date/total_seats/status), notify, per-course registrations.
- Auto-email on `start_date` PATCH via `start_date_updated_html` template — sent to all registrants (paid + pending).
- Broadcast `/api/admin/courses/{code}/notify` with audience filter (all/paid/pending) wraps admin HTML in branded `broadcast_html` shell.
- Public training page now reads `start_date`/`total_seats`/`status` from DB; respects `status === "closed"` with a "Registration closed" UI branch.
- Admin dashboard has Registrations ↔ Courses tab toggle; Courses tab supports inline editing with dirty-state, open/close toggle, new-course creation, and notify modal.
- Registration capacity checks (both `/api/register` and `/api/admin/mark-paid`) read live `course.total_seats` so admin edits take effect immediately.

**Why:** Bassam needed to start new cohorts, change start dates, and communicate with registrants without code edits. Originally the cohort date and capacity were hard-coded in env vars + frontend constants.

**How to apply:** When adding future training courses, POST to `/api/admin/courses` from the admin UI or seed another row; the public page for each course just needs its own route that fetches `/api/courses/{code}`. Backend is branch `feature/registration-backend` (auto-deploys to Render); frontend is `main` (auto-deploys to Cloudflare Pages).

===== project_email_sender_mail_subdomain.md =====
---
name: ProReadyEngineer email sender is mail.proreadyengineer.com
description: Resend sender switched from noreply@promechdirectory.com to info@mail.proreadyengineer.com with DKIM+SPF aligned on the real brand domain — fixes spam-folder delivery
type: project
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---
**Shipped 2026-04-20** — replaces the cross-brand `noreply@promechdirectory.com` sender that was triggering Gmail's spam filter.

**What changed:**
- New verified Resend domain `mail.proreadyengineer.com` (domain ID `445e8811-1c3b-4206-8e48-7d726bcee34c`) alongside existing `promechdirectory.com`.
- Three Cloudflare DNS records added to the `proreadyengineer.com` zone:
  - `TXT resend._domainkey.mail` — DKIM public key
  - `MX send.mail` priority 10 → `feedback-smtp.us-east-1.amazonses.com`
  - `TXT send.mail` — `v=spf1 include:amazonses.com ~all`
- Render env var `EMAIL_FROM` updated to `ProReadyEngineer <info@mail.proreadyengineer.com>`.
- `EMAIL_REPLY_TO` still `info@proreadyengineer.com` so replies land in Bassam's real inbox.

**Why:** The From address domain (`promechdirectory.com`) didn't match the visible brand (`proreadyengineer.com`), and Gmail flagged the first registration confirmation as spam with the "for your security we disabled links" warning. Aligning the sender with the real brand domain + passing DKIM/SPF/DMARC at the mail subdomain fixes this.

**How to apply:** If email deliverability regresses, first confirm:
1. Resend domain still shows `verified` for all 3 records: `curl -H "Authorization: Bearer $RESEND_API_KEY" https://api.resend.com/domains/445e8811-1c3b-4206-8e48-7d726bcee34c`
2. DNS still resolves: `dig @8.8.8.8 +short TXT resend._domainkey.mail.proreadyengineer.com`
3. Render still has the updated `EMAIL_FROM`.
DKIM key rotation would require regenerating via Resend and updating the Cloudflare TXT record in place.

**Not yet done:** DMARC TXT at `_dmarc.proreadyengineer.com` (optional but recommended — Cloudflare is nagging about it on the DNS page). Suggest `v=DMARC1; p=none; rua=mailto:info@proreadyengineer.com` as a monitoring-only starting policy.

===== project_render_deploy_live.md =====
---
name: ProReadyEngineer training-API is deployed on Render
description: Live URL, admin token location, auto-deploy setup, and the psycopg3 dialect gotcha for future sessions
type: project
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---
**Deployed 2026-04-19 ~22:48 UTC**

**Service URL:** https://proreadyengineer-training-api-jd9a.onrender.com
**Service ID:** srv-d7ip5i7avr4c73fs390g
**DB:** proreadyengineer-db-jd9a (Render free Postgres, Oregon)
**Blueprint:** `proreadyengineer-training` (exs-d7ip4gl7vvec73930drg) tracking `bmsabry/proready-website @ feature/registration-backend` via `backend/render.yaml`
**Auto-Deploy:** ENABLED via Render's GitHub App (installed on both `proreadyengineer-mvp` and `proready-website`). Pushes to `feature/registration-backend` auto-redeploy. Don't use the Public Git URL route — it disables auto-deploy.

**Secrets set in Render dashboard (not in render.yaml):**
- `ADMIN_TOKEN` = `gT5crhbIPC1JQbInCZ48MM8kdVSAIpR56padffCDpaQ` (generated 2026-04-19, 32-byte urlsafe)
- `RESEND_API_KEY` = pulled from secrets.env in Drive (value starts `re_XZBw...`)

**Endpoints verified live:**
- GET /, /healthz, /api/seats — all 200
- POST /api/register — creates pending, duplicate detection works, honeypot silently drops
- Admin endpoints (with Bearer token) — list, mark-paid, cancel all working; seats increment/decrement correctly

**psycopg3 dialect gotcha — IMPORTANT:**
Render provides `DATABASE_URL=postgresql://...`. SQLAlchemy resolves that to the psycopg2 driver by default. We ship `psycopg[binary]` v3, not psycopg2. `app/db.py` has a `_normalize_db_url()` helper that rewrites the scheme to `postgresql+psycopg://`. If the deploy ever errors with `ModuleNotFoundError: No module named 'psycopg2'`, check that this normalizer is still in place — don't "fix" it by adding psycopg2-binary to requirements.

**FULL STACK LIVE as of 2026-04-19 ~23:30 UTC:**
- Cloudflare Pages Production + Preview env: `VITE_API_BASE=https://proreadyengineer-training-api-jd9a.onrender.com` set.
- PR #1 (`feature/registration-backend → main`) merged at commit `a73e4e2`. Cloudflare production deploy `a84ba53a.proready-website.pages.dev` succeeded; proreadyengineer.com main bundle confirmed to reference the Render API URL.
- CORS preflight from `https://proreadyengineer.com` returns 200 with proper `access-control-allow-origin`.
- Render Blueprint still tracks `feature/registration-backend`. After the merge, `main` is even with (or ahead of) that branch. Future backend work should either land on `main` directly then cherry-pick/merge into `feature/registration-backend`, OR switch the Blueprint to track `main` in the Render dashboard.

**Outstanding nice-to-have (not blocking registrations):** verify `proreadyengineer.com` sending domain in Resend dashboard. If unverified, applicant confirmation + admin-notification emails silently fail, but registrations themselves still succeed and are stored in the DB.

**Why:** Phase 2 cohort registration backend. Replaces the manual "email me your form data" flow.
**How to apply:** If future work needs the admin token or the live URL, read them here. If the deploy breaks, check Render logs (https://dashboard.render.com/web/srv-d7ip5i7avr4c73fs390g/logs) before changing code.

===== project_seat_count_active.md =====
---
name: Public seat counter = active (paid + pending), not paid-only
description: ProReadyEngineer training-API counts a registration as "taking a seat" the moment the form is submitted; only cancelled rows free a seat
type: project
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---
**The semantic** (decision 2026-04-24, replacing the original 2026-04-19 paid-only model):
- `count_active(db, code)` = paid + pending. THIS is the public seat counter, the registration capacity gate, and the `taken` field returned by `/api/seats`, `/api/register`, and `/api/admin/mark-paid` and `/cancel`.
- `count_paid(db, code)` = paid only. Still used inside `mark-paid` as a defensive guard so admins can't accept payment for more than `total_seats`.
- `CourseOut` exposes BOTH: `seats_taken` = active (public counter), `seats_paid` = paid only (admin breakdown).

**Why this matters**: Bassam initially saw "15 of 15 seats remaining" while 3 real registrations were sitting in pending — the old paid-only counter hid them, which under-reported availability and risked overselling once admin processed the invoices.

**How to apply**:
- The public detail page and listing card show ACTIVE seats.
- Admin Courses tab shows "X paid · Y pending · Z remaining" per course (green/amber/slate).
- Pending → paid transition does NOT change the public counter (correct: the seat was already held).
- Pending → cancelled FREES a seat publicly.
- Capacity guard in `mark-paid` still uses count_paid (specifically so promoting pending→paid works when active >= capacity).
- Don't add a new "convert paid-only into seats_taken" path — single source of truth is `seats.py`.

===== feedback_drive_large_download_workaround.md =====
---
name: Drive MCP write EOF workaround — use curl directly
description: When Drive MCP download_file_content throws "write EOF" on large files (>2MB or so), fall back to curl against drive.google.com/uc?export=download
type: feedback
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---
The Google Drive MCP (`mcp__71c25b3a-*__download_file_content`) intermittently fails with `write EOF` errors for larger binary payloads (PNGs in the multi-MB range). Bassam has asked for this workaround by name — "use the method we used recently".

**Why:** MCP transport chokes on big base64 payloads in a single tool result.

**How to apply:** Bypass the MCP entirely and use curl against the public Drive download URL. The Drive MCP is still useful for discovery (`search_files` to get the file ID), then curl does the bytes.

```bash
FILE_ID="<id from search_files>"
TMP=/tmp/dlfile
curl -sSL -A "Mozilla/5.0" -c /tmp/gdc.cookies \
    "https://drive.google.com/uc?export=download&id=${FILE_ID}" \
    -o "$TMP.htmlprobe" -w "HTTP=%{http_code} SIZE=%{size_download} TYPE=%{content_type}\n"

# If we got HTML (>100MB virus-warning interstitial), extract confirm+uuid and re-request
if file "$TMP.htmlprobe" | grep -qi "HTML"; then
    TOKEN=$(grep -oE 'confirm=[0-9A-Za-z_-]+' "$TMP.htmlprobe" | head -1 | sed 's/confirm=//')
    UUID=$(grep -oE 'uuid=[0-9a-f-]+' "$TMP.htmlprobe" | head -1 | sed 's/uuid=//')
    curl -sSL -A "Mozilla/5.0" -b /tmp/gdc.cookies \
        "https://drive.google.com/uc?export=download&confirm=${TOKEN}&uuid=${UUID}&id=${FILE_ID}" \
        -o "$TMP"
else
    mv "$TMP.htmlprobe" "$TMP"
fi

file "$TMP"  # verify type
```

This is specific to **user's own Drive files** that have already been located via the Drive MCP — it's not a generic web-fetch workaround (the web-fetch restriction still applies to third-party URLs).

===== feedback_google_drive_default.md =====
---
name: Default to Google Drive for project reference files
description: In Cowork, when project instructions reference files (e.g. INSTRUCTIONS_FOR_NEW_AI.md, HANDOVER.md, secrets.env) and they are not in the workspace folder or uploads, search Google Drive first before asking the user.
type: feedback
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---
When project instructions reference supporting files (handover docs, instruction files, secrets, etc.) and they are not present in the selected workspace folder or uploads, the default next step is to search Google Drive using the Drive MCP (`mcp__71c25b3a-8676-40bf-a2b6-a226114723de__search_files`, `read_file_content`, etc.) — do NOT ask the user to upload them.

**Why:** The user (Bassam) has repeatedly said this is the expected Cowork workflow — reference files live in Google Drive, and asking to upload them is wasted effort. He has flagged this "1 million times."

**How to apply:** At the start of any project where instructions mention files that aren't in the workspace, immediately load Drive search tools via ToolSearch (`select:mcp__71c25b3a-8676-40bf-a2b6-a226114723de__search_files,...`) and search by title. Only ask the user if Drive search returns nothing.

===== feedback_persistent_tunnel_pattern.md =====
---
name: Cloudflared preview tunnel — short-lived, NOT persistent
description: When Bassam asks for a preview-before-push, run cloudflared as a short-lived review tunnel (10-30 min). Don't promise persistence — for that, push to main (Cloudflare Pages auto-deploys) or use a Pages preview branch if enabled.
type: feedback
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---

**The big lesson:** Cloudflared quick tunnels in Cowork are **short-lived review tools**, not persistent infrastructure. Stop trying to keep one URL alive across long gaps with watchdogs and scheduled tasks — that approach failed twice and the URL changes on cloudflared restart anyway.

**Correct workflow when Bassam says "show me a preview before we push":**

1. **Edit in working tree, no commit.**
2. **Two short Bash calls to launch (each <2s):**
   ```bash
   # Call 1 — start vite (NEVER use 'npm run dev'; it triggers exit 144 here)
   setsid nohup bash -c 'cd /sessions/magical-focused-ptolemy/proready-website && exec node node_modules/.bin/vite --host 127.0.0.1 --port 5173' >/sessions/magical-focused-ptolemy/vite.log 2>&1 </dev/null &
   disown

   # Call 2 — start cloudflared
   : > /sessions/magical-focused-ptolemy/cloudflared.log
   setsid nohup /sessions/magical-focused-ptolemy/bin/cloudflared tunnel \
     --url http://127.0.0.1:5173 --protocol http2 --no-autoupdate \
     >/sessions/magical-focused-ptolemy/cloudflared.log 2>&1 </dev/null &
   disown
   ```

3. **Third Bash call — verify after 10s sleep:**
   ```bash
   sleep 10
   URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" /sessions/magical-focused-ptolemy/cloudflared.log | head -1)
   echo "$URL" > /sessions/magical-focused-ptolemy/current_preview_url.txt
   curl -fsSL -o /dev/null -w "HTTP=%{http_code}\n" "$URL/"
   ```

4. **Verify HTTP 200, share URL, set expectations:**
   - "Good for ~10–30 minutes of active review"
   - "If it drops while you're reviewing, ask me and I'll restart"
   - "I will NOT keep this alive overnight — that's what main pushes are for"

5. **After approval, commit + push to main.** Cloudflare Pages auto-deploys to proreadyengineer.com in ~1 min.

**What does NOT work — don't repeat:**
- ❌ Scheduled task heartbeat trying to keep tunnel alive every minute. cloudflared quick tunnels get revoked by Cloudflare even with the process running, and the URL changes on every restart anyway. Disable any `proready-tunnel-keepalive` task left over.
- ❌ `npm run dev` — exits 144 (SIGURG-related). Use `node node_modules/.bin/vite` directly.
- ❌ Long polling loops in the same Bash call as the launch — sandbox tear-down kills them mid-poll.
- ❌ Promising the URL will outlive the active review window.

**For genuine "stable preview URL across days" use:**
- Cloudflare Pages preview branch deployments — but this project's Pages config only auto-deploys `main` (per `secrets.env: CLOUDFLARE_PAGES_BRANCH=main`). Preview-branch deploys are NOT enabled. Bassam would need to enable them in the Cloudflare dashboard ("Preview deployments" → "All non-Production branches").
- Until preview branches are enabled in Cloudflare: the only durable preview is push-to-main (changes are usually additive and easily revertable with one commit).

**Files in this project:**
- `/sessions/magical-focused-ptolemy/bin/cloudflared` — binary
- `/sessions/magical-focused-ptolemy/proready-website/.env.local` — VITE_API_BASE → live Render backend (so the tunnel renders real data)
- `/sessions/magical-focused-ptolemy/current_preview_url.txt` — last-seen URL (informational, may be stale)

===== feedback_tunneling_tool.md =====
---
name: Use cloudflared for preview tunnels, not localtunnel
description: For the ProReadyEngineer marketing site (and by extension any project whose handover specifies it), preview tunnels must use cloudflared (`*.trycloudflare.com`), never localtunnel (`*.loca.lt`). Install the binary if missing — do not substitute.
type: feedback
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---
Preview tunnels for the ProReadyEngineer marketing site must use **cloudflared**, producing a `https://*.trycloudflare.com` URL. Do not substitute `localtunnel` / `npx localtunnel` / `*.loca.lt`.

**Why:** The project HANDOVER.md explicitly specifies cloudflared (the script `tunnel-manager.sh` under the `localtunnel-management` folder name is misleading — the script itself runs `cloudflared tunnel --url ...`). Bassam caught the substitution in a prior session ("why did you not use cloud flare tunnel as instructed?"). Localtunnel also adds a password-gate interstitial that cloudflared does not, making review friction higher.

**How to apply:**
- If `cloudflared` is not on PATH in the sandbox, download it: `curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /sessions/<sid>/bin/cloudflared && chmod +x`.
- Start a quick tunnel: `nohup /sessions/<sid>/bin/cloudflared tunnel --url http://127.0.0.1:<vite-port> --no-autoupdate > cloudflared.log 2>&1 &`.
- Grep the URL from the log: `grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" cloudflared.log | head -1`.
- Bind Vite to `127.0.0.1` (not `0.0.0.0`) so only the tunnel exposes it; use `--host 127.0.0.1 --port 5173`.
- The `.a0proj/skills/localtunnel-management/` path referenced in HANDOVER was from the old Agent Zero workspace and is NOT committed to the git repo — don't block on its absence, just invoke cloudflared directly.

===== reference_backup_skill.md =====
---
name: ProReadyEngineer Website backup procedure
description: When Bassam asks to "back up", "refresh the backup", "update backup", or similar for the ProReadyEngineer marketing site project, read and follow the BACKUP_SKILL.md file at the workspace root. It contains the exact overwrite procedure.
type: reference
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---
For the **ProReadyEngineer Website** project, the backup procedure is codified in a skill-style markdown file the user asked me to create. It lives at the workspace root (not in `.claude/skills/`, which is read-only in this Cowork environment):

- Path: `/sessions/<sid>/mnt/ProReadyEngineer Website/BACKUP_SKILL.md`
- Trigger phrases: "back up", "backup the project", "redo the backup", "refresh the backup", "update backup", "do the backup again"

When triggered: Read BACKUP_SKILL.md end-to-end and execute its steps without asking clarifying questions. The skill overwrites four files (`INSTRUCTIONS_FOR_NEW_AI.md` at workspace root + 3 files in `.backup/`) and refreshes the INSTRUCTIONS copy in the shared Drive folder `1tUr6jqDiyC90Hfuk3_D_DTjkJ3EY6tY6`.

The skill is intentionally stored in the workspace folder so it persists to the user's computer via Drive-for-Desktop, and so the user can edit it directly. If the user later asks to modify the backup procedure, edit `BACKUP_SKILL.md` in place.

===== reference_render_and_secrets.md =====
---
name: ProReadyEngineer Render account + secrets locations in Drive
description: Bassam has an existing Render account with a marketplace project (proreadyengineer-mvp). RENDER_API_KEY, GitHub PAT, Stripe, PayPal, Resend, SignWell, AWS S3, DeepInfra keys all live in Google Drive. Do not ask user to provide secrets — check Drive first.
type: reference
originSessionId: 1bde30f9-7812-452b-837b-7c93d5c35efa
---
**Render account:** https://dashboard.render.com (owner bmsabry@gmail.com)

**Existing Render services** (for the separate `proreadyengineer-mvp` B2B marketplace project, NOT the marketing site):
- proreadyengineer-api — FastAPI Python backend → https://proreadyengineer-api.onrender.com
- proreadyengineer-web — Next.js frontend → https://proreadyengineer-web.onrender.com
- proreadyengineer-db — PostgreSQL (Basic-256mb)
- proreadyengineer-redis — Redis
- proreadyengineer-rfq-cron — Cron job, every 15min
- Marketplace GitHub repo: https://github.com/griggril000/proreadyengineer-mvp

**The marketing site (proready-website)** is SEPARATE — statically hosted on Cloudflare Pages from `github.com/bmsabry/proready-website`. Don't conflate them.

**Secrets locations in Drive** (owner bmsabry@gmail.com):

1. Marketing-site handover folder (Drive folder `1tUr6jqDiyC90Hfuk3_D_DTjkJ3EY6tY6`):
   - `HANDOVER.md` (file id `1CRmrf4g1tH4GKMxEs_7qGushychPk4dT`) — marketing site overview
   - `secrets.env` (file id `1_KMhGFzSORJKUQi9kEGQdQ3MOZLwbGkK`) — GitHub PAT, Formspree, Cloudflare domain
   - `proreadyengineer_handover_package.tar.gz` — full package
   - Commits: GitHub PAT from this file is for `bmsabry/proready-website`

2. Marketplace handover folder (Drive folder `1fxMIaKPSQfM64dERI25-xM3W3l1SGFqo`):
   - `HANDOFF.md` (`14XVob-myXd809ZaCJdcJHPllPsz2QnGR`) — marketplace architecture
   - `DEVELOPMENT_HISTORY.md` — decisions, bugs, gotchas
   - `secrets.env` (file id `1nIQk3iQA9MWGHbYyuoEqnoGCiboCk8zj`) — RENDER_API_KEY + all marketplace secrets
   - `SECRETS.md` — reference/doc (no actual values)
   - `README-FOR-NEXT-AGENT.txt` (file id `1AnU1CV-mtqk07yWj5lLgRcpC38_vIqMy`) — orientation

**How to apply:** When a project needs a secret (Render API key, GitHub PAT, Stripe, etc.) and it is not in the current session uploads, immediately search Drive for `secrets.env` or use the file IDs above via `mcp__71c25b3a-*__download_file_content`. Do NOT ask the user to provide secrets before checking Drive.

**Gotchas from handoff docs** (marketplace only — not relevant to the marketing site):
- `OPENAI_API_KEY` actually points to DeepInfra, not OpenAI (`OPENAI_API_BASE=https://api.deepinfra.com/v1/openai`).
- `npm install` for the marketplace frontend needs `--legacy-peer-deps` (React 19 conflicts).
- SignWell webhook endpoint is named `/webhooks/signrequest` for historical reasons — do not rename.
- No Celery worker on Render; RFQ dispatch uses asyncio in FastAPI + a Render Cron Job.
```


---

## Products page + Pro3DWorks download tracking (added 2026-08-04)

**What:** `/products` page (in navbar) offers Pro3DWorks (free single-file browser CAD viewer,
source repo `bmsabry/Pro3DWorks`) for download with full statistics.

**Flow:** button → `GET /download/pro3dworks` → Cloudflare Pages Function
(`functions/download/pro3dworks.js`) which (1) logs `{time, country, region, city, timezone,
colo, referrer, user_agent}` from `request.cf` via `POST {API}/api/track/download`
(fire-and-forget in `waitUntil`; download NEVER breaks on logging failure) and (2) streams the
static asset `public/downloads/Pro3DWorks.html` with `Content-Disposition: attachment` +
`Cache-Control: no-store` (every download must hit the function to be counted). Direct hits to
`/downloads/Pro3DWorks.html` bypass counting — that's accepted.

**Backend** (`backend/app/routes/downloads.py`, model `ProductDownload` in `models.py`,
table auto-created by `create_all` on Render deploy):
- `POST /api/track/download` — insert; product whitelist `KNOWN_PRODUCTS = {"pro3dworks"}`.
- `GET /api/downloads/stats` — public aggregates (total/7d/30d/top countries) for the live
  counter on `/products`. No PII. Unauthenticated by design; repo is public so there is no
  secret between the Pages Function and this endpoint — counts are best-effort marketing
  stats, not billing data.
- `GET /api/admin/downloads` — `require_admin`; daily series, countries, referrers, recent
  100 rows. Surfaced in `/admin` → **Downloads** tab (`DownloadsTab` in AdminDashboard.tsx).

**Updating the shipped app:** rebuild Pro3DWorks, replace `public/downloads/Pro3DWorks.html`,
bump the version string on `src/pages/Products.tsx`, push `main`.

**IP addresses are never stored** — geo stops at city (Cloudflare edge data).

---

## Course dates are fetched at build time, not typed (added 2026-08-18)

**The bug this kills.** Every public course page is prerendered to static HTML
at build time and only swaps to live API data after hydration. So whatever the
component used as its "not loaded yet" default was also what Google, link
previews and no-JS visitors read. Those defaults were hand-typed constants, and
twice they went stale after the cohort moved in the admin dashboard — the site
advertised a cohort that no longer existed (May 2026, 5 days, long after it had
become 29 Aug 2026, 4 days).

**How it works now.**

1. `scripts/fetch-course-data.mjs` runs first in `npm run build`. It reads
   `VITE_API_BASE` (the same variable the browser bundle uses — set in the
   Cloudflare Pages project settings) and pulls `/api/courses/{code}` for every
   code in its `COURSE_CODES` list.
2. It writes `src/data/course-snapshot.json`, which **is committed** — so a
   failed fetch falls back to the last known good data, not to nothing.
3. `src/data/courseSnapshot.ts` exposes it typed. `Training.tsx` and
   `training/GasTurbineEmissionsMapping.tsx` take their prerender fallbacks from
   there instead of literals.
4. `scripts/prerender.mjs` then verifies the emitted HTML actually contains every
   day of the live schedule, and **fails the build** if it doesn't. That is the
   part that makes this stick: reintroducing a hardcoded date stops the deploy
   instead of quietly publishing the wrong cohort.

**Rules it follows.** It never fails the build (Render's free tier sleeps; three
attempts, 45 s each, then the committed snapshot). It refuses to overwrite a good
snapshot with a payload that has no usable dates. It only rewrites the file when a
course fact actually changed, so `generatedAt` doesn't churn the diff. It
deliberately does **not** snapshot seats-taken or price — a stale "3 seats left"
baked into static HTML is worse than the generic label shown until the live fetch
lands.

**Adding a course:** add its code to `COURSE_CODES` in the fetch script, and add
its route to `SCHEDULE_PAGES` in `scripts/prerender.mjs` (`days: 'all'` if the
page publishes a day-by-day timeline, `days: 'start'` if it only shows the start).

**The remaining gap, stated plainly:** prerendered HTML only refreshes when the
site is rebuilt. Change dates in the admin dashboard and the static HTML still
shows the old ones until the next Cloudflare Pages deploy (any push to `main`, or
a manual "Retry deployment"). The browser shows the new dates immediately either
way; it is crawlers and no-JS visitors who see the older ones in between. A
Cloudflare deploy hook fired from the backend on course edit would close it.

**Also fixed here:** `scripts/prerender.mjs` now refuses to run when
`dist/index.html` is already a rendered page. It is both the template and the
output for route `/`, so running it twice without a `vite build` in between used
to write the homepage into all 33 routes.

---

## Attendance confirmation is visible in the admin UI (added 2026-08-18)

`Registration.attendance_confirmed_at` is set automatically when a registrant
replies to a confirm-your-seat broadcast (the support desk records it as the
reply is processed). Until now it was only readable through the AI assistant.

The Registrations tab of a course workspace now shows it directly:

- an **Attendance** column per row — green "Confirmed" with the date, or amber
  "Awaiting reply"
- a **Confirmed** KPI tile (`confirmed / active`, with "N awaiting reply")
- an **unconfirmed** filter chip — the chase list, active rows only
- the CSV export carries an `Attendance confirmed at` column
- **mark confirmed** / **undo** per row, hitting `POST /api/admin/attendance`
  (`{registration_id, confirmed}`), for confirmations that arrive by phone or
  from an address the person didn't register with

Confirming is idempotent — re-confirming keeps the original timestamp, so "when
did they answer" stays true. Cancelled rows are excluded from every count: they
withdrew, so they are not outstanding.

**Correction to §1 of this file:** Render auto-deploys the backend from `main`,
not from `feature/registration-backend` (that branch is stale — its head predates
the support desk). One push to `main` ships both halves.
