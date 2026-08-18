#!/usr/bin/env bash
set -euo pipefail

uvicorn --app-dir 1-app-source-code app.main:app --host 0.0.0.0 --port 8000 &
streamlit run 1-app-source-code/dashboard/dashboard.py --server.address 0.0.0.0 --server.port 8501
