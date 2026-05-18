# Readers Quest

A quest-based reward engine that tracks individual accomplishments and party goals. Build themed quests for any activity — reading, chores, sports, or anything with trackable progress. Members earn XP and Gold, unlock achievements, redeem prizes, and work together on Co-Op goals.

## Features

- Activity-agnostic quest engine (reading, chores, sports, anything)
- Admin-defined activity types per quest with flexible earning rules
- Themed quests with configurable labels per member (Pokemon trainer, Cheer camp, etc.)
- Individual progress tracking with level vials and milestone markers
- Spendable currency shop for prize redemption
- Co-Op party goals with fairness validation
- Side quests for bonus XP
- Lifetime achievements spanning all quests
- Activity log history and stats

## Quick Start

```
docker compose up
```

Access at `http://localhost:5000`

## Development

```
docker compose --profile dev up
```

See `.github/copilot-instructions.md` for development practices.

## Design

- Self-hosted on local network
- SQLite storage (no external database required)
- Admin PIN for parent access; kids select their profile directly
- Lightweight frontend with minimal dependencies

## Security

- No internet-facing services required
- Admin actions gated behind PIN
- All data stored locally in SQLite
