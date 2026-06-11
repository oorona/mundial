# Documentation Restructuring Plan

## Goal
Restructure the project documentation to improve clarity, separate concerns, and highlight AI capabilities.

## User Review Required
- **Specs Format**: `specs.txt` will be a plain text file in `specs/`.
- **License**: Will be created as `LICENSE` (MIT).

## Proposed Changes

### 1. File Structure Changes
- **Root**:
    - [MODIFY] `README.md`: New AI-focused marketing/intro.
    - [NEW] `LICENSE`: MIT License text.
- **`docs/`**:
    - [NEW] `INSTALLATION.md`: Installation & Prerequisites.
    - [NEW] `CONFIGURATION.md`: Environment variables & secrets.
    - [MODIFY] `ARCHITECTURE.md`: Technical details (update with Gemini info if needed).
    - [KEEP] `DEVELOPER_MANUAL.md`: Guide for new bots.
    - [KEEP] `AI_CAPABILITIES.md`: Detailed AI docs.
    - [DELETE] `DISCORD_APP_SETUP.md`: Merge into Installation/Config.
    - [DELETE] `LLM_USAGE_GUIDE.md`: Merge into AI Capabilities or Developer Manual.
- **`specs/`**:
    - [NEW] `specs.txt`: Comprehensive text capabilities list.
    - [DELETE] `docs/`: Move contents to `docs/` or delete.
    - [DELETE] `README.md`, `docker-compose.yml`, etc. inside `specs/`: Clean up if they are duplicates.

### 2. Content Details

#### `README.md`
- **Headline**: "Baseline: The AI-Native Discord Framework"
- **Features**: Focus on Gemini 3, Multimodal, Thinking Models, Tool Use.
- **Links**: Installation, Config, Architecture, Developer Manual.

#### `specs/specs.txt`
- Plain text list of all capabilities:
  - Core Bot (Auth, Sharding, Permissions)
  - AI (Gemini 3, OpenAI, Anthropic, Image Gen, structured output, caching)
  - Backend/Frontend (FastAPI, Next.js, Dashboard)

#### `docs/INSTALLATION.md`
- Docker setup.
- Prerequisites (Discord App, Secrets).

#### `docs/CONFIGURATION.md`
- `.env` variables.
- Secret files.

#### `docs/ARCHITECTURE.md`
- Diagram/Text explaining Bot <-> Backend <-> DB <-> LLM Service.

## Verification Plan

### Manual Verification
1.  **Check Links**: Verify all links in `README.md` point to correct `docs/` files.
2.  **Readability**: Ensure `specs.txt` is clear and `README.md` is "wow" factor.
3.  **File Existence**: Confirm file moves and deletions.
