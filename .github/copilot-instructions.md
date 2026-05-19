# QuestSmith - Development Instructions

## Branching & Releases

- Use GitHub as the remote repository
- Always publish to a `dev` branch using feature branches (e.g., `feature/ledger-engine`)
- Feature branches are pushed to `dev` automatically by the developer
- Only the project owner creates PRs from `dev` to `main`
- Only the project owner creates GitHub releases
- Maintain a `VERSION` file; ensure it reflects the appropriate version before any merge to `main`

## CI/CD

- Pushing to `dev` triggers an automated dev tag package for testing
- Pushing to `main` triggers an automated build of the latest package

## Development Practices

- Break disparate tasks into individual approaches; never lump unrelated work together
- Always check `dev` commit history vs `main` when starting new tasks
- Docker is the preferred environment for both the end result and testing
- Minimize host changes; use virtual environments or Docker local builds for testing
- Unit tests are required as we approach a release

## Audits

- Every audit considers security, performance, best practices, and reusability
- Use the rubber duck method for audits
- Any new feature addition or full feature removal requires a full audit after implementation

## Backwards Compatibility

- The application is currently in alpha
- Breaking changes for existing implementations are acceptable until the application is released
- Once released, only backwards-compatible changes will be honored

## Documentation

- Maintain the README for public consumption with instructions, feature highlights, and design
- README content should not be technical or lengthy; focus on purpose, features, design, and security
- No emojis in any documentation

## Internal Context

- Track functional design and application framework internally (not for public review)
- These copilot instructions serve as the persistent development context

## Technology Stack

- Backend: Python (Flask)
- Frontend: Alpine.js + Tailwind CSS
- Storage: SQLite (file-based)
- Deployment: Docker, self-hosted on local home network
- Auth: Simple admin PIN code

## Architecture Notes

- Generic quest-based reward engine; activity-agnostic by design
- Quests define activity types, earning rules, theme, and labels
- Lifetime stats and achievements exist outside of quests (permanent member-level data)
- Quests are time-bound campaigns with scoped XP, Gold, prizes, and Co-Op goals
- Activity logs feed both lifetime stats and active quest progression
- Theme language is configurable per quest and per member enrollment
- "Member" is the generic data term; themed per quest (reader, trainer, player, etc.)
