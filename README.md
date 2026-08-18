# Project-Fosu-Smart-Border-Ingress-Alert-System-MVP-
A prototype border-crossing logging, mapping, and threshold-alert system that covers **the whole border**, not just a handful of named checkpoints.

## Run locally

```bash
source .venv/bin/activate
uvicorn --app-dir 1-app-source-code app.main:app --reload --port 8000
streamlit run 1-app-source-code/dashboard/dashboard.py
```

Open `http://localhost:8501`. The dashboard is protected by a session login and does not request operational API data until authentication succeeds.

## Run with Docker

Build and start the API and dashboard with Compose:

```bash
docker compose up --build -d
```

Compose loads dashboard credentials from `.env`, publishes ports `8000` and `8501`, and persists SQLite data in the `fosu-data` named volume.

View logs or stop the application with:

```bash
docker compose logs -f
docker compose down
```

Open the dashboard at `http://localhost:8501` or the API documentation at `http://localhost:8000/docs`.

## Dashboard credentials

Credentials are read from the ignored `.env` file as `FOSU_DASHBOARD_USERNAME` and a one-way `FOSU_DASHBOARD_PASSWORD_HASH`. Rotate them with:

```bash
python 1-app-source-code/scripts/set_dashboard_password.py --username fosu.admin
```

The command prompts for the password without displaying it, writes a salted scrypt hash, and never stores the plain-text password. Reload the login page after changing credentials. In deployment, provide the same environment variables through the hosting platform's secret manager instead of committing `.env`.
