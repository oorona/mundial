#!/bin/bash
set -e

echo "🚀 Starting deployment..."

# Pull latest changes
echo "📥 Pulling latest changes..."
git pull origin main

# Build and start services — single consolidated docker-compose.yml (Traefik-based);
# only .env differs between local and prod.
echo "🔨 Building and starting services..."
docker compose up -d --build

# Run migrations — `heads` (plural): plugin migrations are independent Alembic
# branches, so there is more than one head. `upgrade head` (singular) errors.
echo "🔄 Running database migrations..."
docker compose exec backend alembic upgrade heads

echo "✅ Deployment complete!"
echo "📊 Service status:"
docker compose ps
