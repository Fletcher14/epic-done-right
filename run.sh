#!/bin/bash
# Starts both services and stops them together on Ctrl-C.
cd "$(dirname "$0")"
PY=./.venv/bin/python; [ -x "$PY" ] || PY=$(command -v python3 || command -v python)
"$PY" hospital/app.py & HOSP=$!
sleep 1
"$PY" epcr/app.py & EPCR=$!
echo ""
echo "  Hospital (Epic FHIR side): http://localhost:8001   (chart view: /chart/pt-001)"
echo "  ePCR (crew side):          http://localhost:8002   <- open this"
echo "  Ctrl-C to stop both."
trap "kill $HOSP $EPCR 2>/dev/null" INT
wait
