# Readers Quest

A book reading tracker that rewards readers through themed quests. Track reading progress, earn XP and Gold, unlock achievements, and compete in Co-Op family goals.

## Features

- Themed quests per reader (custom earning rules, labels, and visuals)
- Individual progress tracking with level vials and milestone markers
- Spendable currency shop for prize redemption
- Co-Op family goals with fairness validation
- Side quests for bonus XP
- Lifetime achievements spanning all quests
- Reading log history and stats

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
