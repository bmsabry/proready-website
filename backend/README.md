# ProReadyEngineer Training API

FastAPI backend for cohort registration. Powers the Gas Turbine Emissions
Mapping training page on https://proreadyengineer.com.

## Endpoints

### Public
| Method | Path             | Purpose |
|--------|------------------|---------|
| GET    | `/api/seats`     | `{ taken, capacity, cohort }` — `taken` counts only paid seats. |
| POST   | `/api/register`  | Create a pending lead. Returns `{ ok, taken, status, registration_id }`. |
| GET    | `/healthz`       | Liveness probe used by Render. |

### Admin (requires `Authorization: Bearer $ADMIN_TOKEN`)
| Method | Path                          | Purpose |
|--------|-------------------------------|---------|
| GET    | `/api/admin/registrations`    | List all rows for the active cohort, newest first. |
| POST   | `/api/admin/mark-paid`        | Body: `{ registration_id, notes? }` — flips pending → paid. |
| POST   | `/api/admin/cancel`           | Body: `{ registration_id, notes? }` — flips any → cancelled. |

## Local development

```bash
cd backend
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then edit ADMIN_TOKEN at minimum
uvicorn app.main:app --reload --port 8000
```

Visit http://localhost:8000/docs for the auto-generated OpenAPI UI.

With `RESEND_API_KEY` blank, emails are logged to stdout instead of sent —
this lets you run the full registration flow without any email credentials.

## Deploy to Render

1. Push this repo to GitHub.
2. In Render: **New → Blueprint** → point at this repo.
3. Render reads `backend/render.yaml` and provisions:
   - A free Web Service (`proreadyengineer-training-api`)
   - A free Postgres database (`proreadyengineer-db`)
4. After provisioning, open the web service → **Environment** and set the
   two secrets (`sync: false` in the blueprint):
   - `RESEND_API_KEY` — from `secrets.env` in the shared Drive folder
   - `ADMIN_TOKEN` — generate with
     `python -c "import secrets; print(secrets.token_urlsafe(32))"`,
     save it back to `secrets.env`
5. Trigger a deploy. Once green, hit `https://<service>.onrender.com/healthz`.
6. Update the frontend: set `VITE_API_BASE` to the Render URL in
   Cloudflare Pages env vars and redeploy.

## Marking a registration paid

```bash
curl -X POST https://<service>.onrender.com/api/admin/mark-paid \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"registration_id": 7, "notes": "Stripe payment id pi_xxx"}'
```

The response includes the new `taken` count, which the public site picks up
on the next `/api/seats` poll.

## Listing registrations

```bash
curl https://<service>.onrender.com/api/admin/registrations \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq
```

## Anti-spam

- **Honeypot field** `website` on the registration payload — bots fill all
  fields, real users leave it blank. Submissions with a non-empty `website`
  are silently accepted (200 OK with current taken count) and dropped.
- **Email idempotency** — re-submitting with the same email returns
  `status: "duplicate"` instead of creating a second row.

## Operational notes

- Free Render web services sleep after 15 min of inactivity. First request
  after a sleep takes ~30s. Acceptable for a registration form. Upgrade to
  Starter ($7/mo) if cold-starts become a problem.
- Free Render Postgres has a 90-day max retention. Migrate to a paid plan
  before the cohort closes if you want long-term audit history.
- Schema changes require restarting the web service (tables are created on
  startup via `Base.metadata.create_all`). Add Alembic if the model grows
  beyond this single table.
