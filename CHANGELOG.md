# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

On each tagged release (`vX.Y.Z`), the CI workflow publishes the matching
section below as the GitHub Release notes.

## [Unreleased]

## [0.3.0] - 2026-07-02

### Added
- **Categories tab** for managing your own spending categories: add, rename,
  and delete them, with per-category line counts and totals. Deleting a category
  that still has budget lines is blocked to prevent accidental data loss. Adding
  and renaming go through the same keyboard shortcuts as the Data tab (`Ctrl+3` /
  `Alt+G` to reach the tab).

### Changed
- The MariaDB `budget_items` table now uses `AUTO_INCREMENT` so new categories
  get an id automatically. Databases created by v0.2.0 are migrated in place on
  startup (a guarded `ALTER TABLE`), so existing central databases keep working.

## [0.2.0] - 2026-07-01

### Added
- Optional central **MariaDB** backend via a `budget.ini` config file
  (`configparser` + `pymysql`). The app uses its local SQLite database by
  default, switches to MariaDB when credentials are supplied, shows the active
  database in the title bar, and falls back to SQLite (with a warning) if the
  server is unreachable or `pymysql` is missing. See `budget.ini.example`.

## [0.1.0] - 2026-07-01

First release of **The Simple Budget** — a self-contained desktop budget
tracker built with Python/Tkinter.

### Added
- Track spending: add, edit, and delete budget lines (store, price, date,
  category) in a table.
- Chart tab: total spend (GBP) as a column graph, grouped by category, year, or
  month.
- Full keyboard accessibility: menu bar, tab mnemonics, and shortcuts for every
  action, so the app can be driven entirely without a mouse.
- Read chart aloud: the chart is spoken as plain-language text via `pyttsx3` for
  visually impaired users, with a live on-screen transcript, a voice picker, and
  a speaking-speed slider.
- Cross-platform standalone binaries (Windows, macOS, Linux) built by a
  GitHub Actions workflow and attached to each tagged release.

### Notes
- Binaries are unsigned: macOS Gatekeeper and Windows SmartScreen will warn on
  first launch (right-click → Open on macOS; More info → Run anyway on Windows).
- The macOS build targets Apple Silicon (arm64).
- The read-aloud feature needs eSpeak on Linux (`sudo apt-get install espeak`).

[Unreleased]: https://github.com/mediaswing/the-simple-budget/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/mediaswing/the-simple-budget/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mediaswing/the-simple-budget/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mediaswing/the-simple-budget/releases/tag/v0.1.0
