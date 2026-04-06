## What does this PR do?

<!-- Describe the change in 1-3 sentences -->

## Why?

<!-- What problem does it solve? Link to the GitHub Issue if applicable -->

Closes #

## Type of change

- [ ] New connector
- [ ] New hypothesis
- [ ] Core feature / fix
- [ ] RFC
- [ ] Documentation
- [ ] CI / tooling

## Checklist

- [ ] I have read `CONTRIBUTING.md`
- [ ] My code follows the `CLAUDE.md` guidelines
- [ ] I have added tests for my changes
- [ ] All tests pass (`npm test`)
- [ ] No TypeScript errors (`npm run typecheck`)
- [ ] Linting passes (`npm run lint`)
- [ ] **No secrets, API keys, or real health data in this PR**
- [ ] I have updated documentation if needed

## For connectors:

- [ ] Implements the `HealthConnector` interface
- [ ] Includes `.env.example` with configuration template
- [ ] Includes README explaining what it does and how to configure it
- [ ] Tests use synthetic data only
