# Docker Secrets Setup Guide

This directory contains all sensitive credentials for the bot platform. These files are used by Docker Compose secrets mechanism.

## Security Best Practices

⚠️ **CRITICAL**: Never commit secret files to version control!

Add to `.gitignore`:
```
secrets/
*.txt
.env
```

## Creating Secret Files

Run this script to create all required secret files:

```bash
#!/bin/bash
# setup-secrets.sh

mkdir -p secrets

echo "Creating secret files..."

# Discord Secrets
# (See ../docs/DISCORD_APP_SETUP.md if you haven't created a bot yet)
read -p "Enter Discord Bot Token: " discord_bot_token
echo "$discord_bot_token" > secrets/discord_bot_token.txt

read -p "Enter Discord Client Secret: " discord_client_secret
echo "$discord_client_secret" > secrets/discord_client_secret.txt

# API Secret
echo "Generating API secret key..."
api_secret=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo "$api_secret" > secrets/api_secret_key.txt

# LLM API Keys (optional)
read -p "Enter OpenAI API Key (or press Enter to skip): " openai_key
echo "${openai_key:-sk-placeholder}" > secrets/openai_api_key.txt

read -p "Enter Google API Key (or press Enter to skip): " google_key
echo "${google_key:-placeholder}" > secrets/google_api_key.txt

read -p "Enter Anthropic API Key (or press Enter to skip): " anthropic_key
echo "${anthropic_key:-sk-ant-placeholder}" > secrets/anthropic_api_key.txt

read -p "Enter xAI API Key (or press Enter to skip): " xai_key
echo "${xai_key:-placeholder}" > secrets/xai_api_key.txt

# Set restrictive permissions
chmod 600 secrets/*.txt

echo "✅ All secret files created successfully!"
echo "Files are readable only by owner (chmod 600)"
echo ""
echo "⚠️  IMPORTANT: Update .env file with your PostgreSQL and Redis connection strings:"
echo "   DATABASE_URL=postgresql://user:pass@host:port/db"
echo "   REDIS_URL=redis://:pass@host:port/db"
```

## Manual Setup

Alternatively, create each file manually:

### 1. Discord Secrets

```bash
echo "your_bot_token_here" > secrets/discord_bot_token.txt
echo "your_client_secret_here" > secrets/discord_client_secret.txt
```

### 2. API Secret

```bash
# Generate random secret
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/api_secret_key.txt
```

### 3. LLM API Keys

```bash
echo "sk-your-openai-key" > secrets/openai_api_key.txt
echo "your-google-key" > secrets/google_api_key.txt
echo "sk-ant-your-anthropic-key" > secrets/anthropic_api_key.txt
echo "your-xai-key" > secrets/xai_api_key.txt
```

### 4. Database Configuration

Since you're using external PostgreSQL and Redis, configure connection strings in `.env`:

```bash
# Edit .env file
DATABASE_URL=postgresql://your_user:your_password@your_db_host:5432/your_database
REDIS_URL=redis://:your_password@your_redis_host:6379/0
```

## File Structure

After setup, you should have:

```
secrets/
├── discord_bot_token.txt
├── discord_client_secret.txt
├── api_secret_key.txt
├── openai_api_key.txt
├── google_api_key.txt
├── anthropic_api_key.txt
└── xai_api_key.txt
```

**Plus** in your `.env` file:
```
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
```

## Permissions

Ensure files have restrictive permissions:

```bash
chmod 600 secrets/*.txt
```

## How Docker Secrets Work

1. Docker Compose mounts secret files as read-only to `/run/secrets/` in containers
2. Application reads secrets from files at runtime
3. Secrets never appear in environment variables or logs
4. Each service only has access to secrets it needs

## Production Deployment

For production, use:
- **Docker Swarm Secrets**: Built-in orchestration secrets
- **Kubernetes Secrets**: For K8s deployments
- **AWS Secrets Manager**: For AWS
- **HashiCorp Vault**: For enterprise secret management

## Verifying Secrets

Test that secrets are loaded correctly:

```bash
# Start services
docker-compose up -d

# Check backend can read secrets
docker-compose exec backend python -c "
import os
print('API Secret:', os.getenv('API_SECRET_KEY')[:10] + '...')
"

# Check bot can read secrets
docker-compose exec bot python -c "
import os
print('Bot Token:', os.getenv('DISCORD_BOT_TOKEN')[:10] + '...')
"
```

## Rotating Secrets

To rotate a secret:

1. Update the secret file
2. Restart affected services:
   ```bash
   docker-compose restart backend bot
   ```

## Backup

Backup secrets to encrypted storage:

```bash
# Create encrypted backup
tar czf - secrets/ | gpg -c > secrets-backup.tar.gz.gpg

# Restore
gpg -d secrets-backup.tar.gz.gpg | tar xzf -
```

---

**Never commit secrets to version control!**
