#!/bin/bash
# Activate virtual environment and set environment variables

# Activate venv
source .venv/bin/activate

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

echo "✅ ServiceScope environment activated!"
echo "📦 Python: $(which python)"
echo "🗄️  Database: $POSTGRES_DB@$POSTGRES_HOST:$POSTGRES_PORT"
echo ""
echo "Quick commands:"
echo "  python app/main.py          # Start FastAPI server"
echo "  alembic upgrade head        # Run database migrations"
echo "  pytest                      # Run tests"
echo "  deactivate                  # Exit environment"
