#!/bin/bash
# Starts both services and stops them together on Ctrl-C.
cd "$(dirname "$0")"
python hospital/app.py & HOSP=$!
sleep 1
python epcr/app.py & EPCR=$!
echo ""
echo "  Hospital (Epic FHIR side): http://localhost:8001"
echo "  ePCR (crew side):          http://localhost:8002   <- open this"
echo "  Ctrl-C to stop both."
trap "kill $HOSP $EPCR 2>/dev/null" INT
wait
