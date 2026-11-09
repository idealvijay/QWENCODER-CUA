$ErrorActionPreference = "Stop"
py -3.11 -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[windows,dev]"
python scripts/doctor.py
