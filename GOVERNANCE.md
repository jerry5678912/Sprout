# Sprout Project Governance

Sprout is a community-driven programming language project. Language quality,
consistency, and long-term maintainability take priority over feature count.

## Project Direction

Sprout should remain approachable, practical, game-friendly,
engineering-friendly, and contributor-friendly. The project's current
priorities are:

- stability and runtime maturity;
- usability and professional tooling;
- documentation and contributor experience;
- package ecosystem growth; and
- responsible public adoption.

Features are not added merely because another language has them. Prefer
consistency, clear diagnostics, maintainable implementation, and documented
user value over feature accumulation.

## Decisions and Proposals

Issues are the main place for design discussion. Pull requests are the main
place for reviewed code changes. `ROADMAP.md` records project direction, and
`CONTRIBUTING.md` defines the contribution workflow.

Large changes should begin with an issue before implementation. This includes:

- new syntax or keywords;
- changes to runtime behavior or VM architecture;
- changes to package formats or dependency resolution;
- major standard-library or ecosystem additions; and
- changes with broad tooling, documentation, or compatibility effects.

Proposals are evaluated by their language consistency, implementation
complexity, maintenance cost, user value, tooling impact, documentation impact,
VM impact, and ecosystem impact.

## Contributions

Bug fixes, tests, documentation, examples, performance work, editor support,
packaging, and ecosystem tooling are welcome. Contributions should be focused,
tested, documented where needed, and aligned with the roadmap.

When work overlaps:

- collaborate instead of creating competing rewrites;
- preserve contributor credit;
- coordinate through the relevant issue or pull request;
- rebase when appropriate; and
- avoid merging duplicate implementations.

Maintainers may defer or decline a technically valid change when its ongoing
cost outweighs its benefit or when it conflicts with Sprout's direction.

## License

Sprout is licensed under the Apache License 2.0. Contributions submitted to the
project are accepted under the same license. See `LICENSE`, `NOTICE`, and the
licensing section of `CONTRIBUTING.md`.

