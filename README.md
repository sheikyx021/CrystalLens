# CrystalLens

A Flask-based platform for automated, evidence-driven social media analysis for employee/candidate screening. Scraping via Apify, analysis via local Ollama or Google Gemini, and reporting via a secure dashboard. Dev uses SQLite; prod uses PostgreSQL.

## Features (MVP)
- Employee management with social accounts
- Apify scrapers: Twitter and Facebook
- LLM analysis via Ollama (local) or Gemini (cloud)
- Dashboard and detailed analysis reports
- Export reports to PDF and CSV
- RBAC with roles: system_admin, platform_manager, reviewer
- Audit logging of user actions

## Tech Stack
- Backend: Flask, SQLAlchemy
- DB: SQLite (dev), PostgreSQL (prod)
- Auth: Flask-Login
- LLM: Ollama local API or Google Gemini (gemini-2.0-flash)
- Scraping: Apify Client

## Quickstart (Development)

1) Create a virtual environment and install dependencies
```python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Configure environment (dev uses SQLite by default)
```bash
cp .env.example .env
# Edit .env if needed. For dev you can keep SQLite.
# Set APIFY_API_TOKEN (required for scraping)
# If using Ollama: ensure it is running and a model is pulled (e.g. llama3.1:8b, qwen2.5:7b-instruct)
# If using Gemini: set GOOGLE_API_KEY and select ANALYSIS_PROVIDER=gemini in Settings
```

3) Initialize database and create an admin user
```python
python scripts/seed_admin.py
# You will be prompted for username, email, and password.
```

4) Run the app
```python
python run.py
# Open http://127.0.0.1:5000
```

## Apify Integration
- Twitter Actor: `61RPP7dywgiy0JPD0`
- Facebook Actor: `KoJrdxJCTtpon81KY`
- Configure APIFY_API_TOKEN in `.env`.
- Start jobs from the employee detail page or the Scraping pages.

## LLM Providers
### Ollama (local)
- Configure `OLLAMA_API_URL` and `OLLAMA_MODEL` in `.env`.
- Ensure the model is downloaded in Ollama (e.g., `ollama pull llama3.1:8b` or `qwen2.5:7b-instruct`).
- Test from System page.

### Gemini (cloud)
- Set `GOOGLE_API_KEY` in `.env` or via Settings.
- In Settings → Analysis Settings, choose Provider = `Gemini` and click "Test Gemini".
- Default model is `gemini-2.0-flash`.

## Roles
- system_admin: full access, system settings
- platform_manager: manage employees, trigger scraping/analysis
- reviewer: read-only access to reports

## Production Notes
- Use PostgreSQL and set `DATABASE_URL` accordingly.
- Consider TLS termination via reverse proxy (nginx) and run with `gunicorn`.
- Enable DB encryption at rest and harden .env/secrets storage.
- Integrate CSRF protection for all forms and add stronger session settings.
- Add proper migrations (e.g., Flask-Migrate/Alembic).

## Security Considerations
- API keys in `.env`
- RBAC checks on sensitive endpoints
- Audit logs for critical actions
- Use Ollama for on‑prem analysis when sensitive data must not leave your infra.

## Directory Structure
```
app/
  analysis/
  auth/
  employees/
  main/
  scraping/
  services/
  templates/
config.py
run.py
scripts/seed_admin.py
```

## Troubleshooting
- If login redirects back to login, ensure an admin user exists and you are using the right credentials.
- If scraping fails, verify `APIFY_API_TOKEN` and that the actors are available.
- If analysis fails, ensure the selected provider is configured:
  - Ollama: `ollama serve`, models in `/api/tags`
  - Gemini: correct `GOOGLE_API_KEY` and Provider set to `Gemini`

## License
MIT License. See `LICENSE`.
