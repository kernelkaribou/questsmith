<p align="center">
  <img src="app/static/img/logo-256.webp" alt="QuestSmith Logo" width="128">
</p>

<h1 align="center">QuestSmith</h1>
<p align="center"><em>Forge Your Adventure</em></p>

A quest-based reward engine that tracks individual accomplishments and party goals. Build themed quests for any activity — reading, chores, sports, or anything with trackable progress. Members earn currency, unlock achievements, redeem prizes, and work together on Co-Op goals.

## Features

- Activity-agnostic quest engine (reading, chores, sports, anything)
- Admin-defined activity types per quest with flexible earning rules
- Themed quests with configurable labels per member (Dungeon Exploration, Artifacts hunt, etc.)
- Individual progress tracking with level vials and milestone markers
- Spendable currency shop for prize redemption
- Co-Op party goals with fairness validation
- Side quests for bonus XP
- Lifetime achievements spanning all quests
- Activity log history and stats

## Quick Start

```bash
docker compose up
```

Access at `http://localhost:5000`

Admin PIN: `1234` (configure via `ADMIN_PIN` environment variable)

## Development

```bash
# Using Docker dev profile (hot reload)
docker compose --profile dev up

# Or directly with Python
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask db upgrade
python seed.py          # optional: load example data
flask run --debug
```

Run tests:
```bash
pytest tests/
```

See `.github/copilot-instructions.md` for development practices.

## Design

- Self-hosted
- SQLite storage (no external database required)
- Admin PIN for management access; Users select their profile directly
- Lightweight frontend with minimal dependencies

## Security

- No internet-facing services required
- Admin actions gated behind PIN
- All data stored locally in SQLite
