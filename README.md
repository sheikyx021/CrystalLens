<div align="center">

# CrystalLens

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)  
[![Made with Flask](https://img.shields.io/badge/Made%20with-Flask-000?logo=flask&logoColor=white)](#)  
[![LLM: Ollama](https://img.shields.io/badge/LLM-Ollama-0b2a2a.svg)](#)  
[![LLM: Gemini](https://img.shields.io/badge/LLM-Gemini-4285F4.svg)](#)

**Evidence-driven social media analysis for sensitive roles — on-prem with Ollama or fast in the cloud with Gemini.**

</div>

---

## ⚠️ Disclaimer
This project is built **for educational and research purposes only**.  
It is **not intended for real employee surveillance or unlawful use**.  
Always comply with local laws, regulations, and platform Terms of Service.  


## ✨ Features & Highlights
- **Employee & Accounts Management**  
  Create employee profiles, attach social media accounts, and manage linked evidence.  

- **Scraping Automation**  
  Trigger **Apify scrapers** (Twitter / Facebook) from the dashboard and monitor live job status.  

- **AI-Powered Analysis**  
  Choose between:  
  - **Single-request mode**: Quick and lightweight.  
  - **Staged analysis**: Evidence → structured findings → assessment (for accuracy & explainability).  

- **Specific Assessments**  
  Automatically evaluate evidence across dimensions like:  
  - Political / religious orientation  
  - Bias & affiliations  
  - Personal issues & behavioral signals  
  - Violence tendencies  
  - Role suitability  

- **Reporting**  
  Generate **evidence-backed narratives** with citations. Export as:  
  - PDF reports  
  - CSV datasets  
  - Interactive dashboards  

- **RBAC & Auditing**  
  - Roles: `Admin`, `Manager`, `Reviewer`  
  - Audit logs track all sensitive actions for compliance  

---

## 🚀 Quickstart (Dev)
1. **Setup environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Configure `.env`**
   ```bash
   cp .env.example .env
   # APIFY_API_TOKEN=...
   # OLLAMA_API_URL=http://localhost:11434
   # OLLAMA_MODEL=llama3.1:8b
   # GOOGLE_API_KEY=...
   # ANALYSIS_PROVIDER=ollama|gemini
   ```
3. **Seed an admin**
   ```bash
   python scripts/seed_admin.py
   ```
4. **Run server**
   ```bash
   python run.py
   # visit http://127.0.0.1:5000
   ```

---

## ⚙️ Configuration
| Variable            | Purpose                                   |
|---------------------|-------------------------------------------|
| `DATABASE_URL`      | PostgreSQL (prod) / SQLite (dev)          |
| `APIFY_API_TOKEN`   | Required for social scraping              |
| `OLLAMA_API_URL`    | Local Ollama LLM endpoint                 |
| `OLLAMA_MODEL`      | Example: `llama3.1:8b` / `qwen2.5:7b-instruct` |
| `GOOGLE_API_KEY`    | For Gemini integration                    |
| `ANALYSIS_PROVIDER` | Choose: `ollama` (local) or `gemini` (cloud) |

---

## 🤖 Providers
- **Ollama (Local, On-Prem)**  
  - Run `ollama serve`  
  - Pull models: `ollama pull llama3.1:8b`  
  - Best choice when privacy/compliance requires no data leaves your infra  

- **Gemini (Cloud, Google)**  
  - Low latency, clean JSON formatting  
  - Configure via `GOOGLE_API_KEY` in `.env`  
  - Test connection via **Settings → Test Gemini**  

---

## 🔒 Security Practices
- Never commit `.env` or API keys  
- RBAC for access control  
- Audit logging for accountability  
- HTTPS recommended in production  

---

## 📊 Roadmap
- [ ] Add LinkedIn & Instagram scrapers  
- [ ] AI-assisted risk scoring dashboard  

---

## 🤝 Contributing
Contributions welcome!  
- Open an **issue** before large changes  
- Follow security guidelines (no secrets in commits)  
- Submit **PRs** with tests when possible  

---

## 📄 License
MIT — see [`LICENSE`](LICENSE).  

---


