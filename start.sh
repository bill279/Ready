#!/bin/bash
set -e

echo "Starting Executive Assistant..."

# Backend
cd backend
if [ ! -d "venv" ]; then
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
else
  source venv/bin/activate
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "⚠️  Created backend/.env — please fill in your API keys before continuing."
  exit 1
fi

uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Frontend
cd ../frontend
if [ ! -d "node_modules" ]; then
  npm install
fi
npm run dev &
FRONTEND_PID=$!

echo "✅ Backend: http://localhost:8000"
echo "✅ Frontend: http://localhost:5173"
echo "Press Ctrl+C to stop both servers"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
