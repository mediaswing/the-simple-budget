# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

On each tagged release (`vX.Y.Z`), the CI workflow publishes the matching
section below as the GitHub Release notes.

## [Unreleased]

## [0.6.0] - 2026-07-12

### Added
- **Auto-update**: the app now checks GitHub Releases for a newer version a
  couple of seconds after startup, and offers a **Check for Updates…** item
  in the Help menu. When a newer build is available, confirming downloads
  and installs it in place before relaunching (built/frozen copies only;
  running from source instead opens the release page in your browser).

## [0.5.2] - 2026-07-07

### Fixed
- `open_db` no longer crashes on startup when `budget.ini` configures a
  SQLite `path` that can't be opened (missing directory, permissions,
  etc.) — it now falls back to the internal database with a warning,
  matching the existing MariaDB fallback behaviour.
- `gbp()` and `spoken_gbp()` formatted negative amounts incorrectly
  (`£-5.00`, "-1 pounds and -50 pence"); they now render as `-£5.00` and
  "minus 1 pound and 50 pence".

## [0.5.1] - 2026-07-03

### Fixed
- macOS and Linux downloads failed to launch ("permission denied" / a generic
  error) because the release pipeline stripped the executable bit: GitHub's
  `upload-artifact` doesn't preserve Unix permissions. Each platform's build is
  now zipped on its own build machine (via `ditto` on macOS, `zip` on Linux) so
  permissions — and the macOS ad-hoc signature — survive download. No more
  `chmod +x` needed after unzipping.

## [0.5.0] - 2026-07-02

### Added
- **Access control for Windows AD / Microsoft Entra.** An administrator can add
  an `[access]` section to `budget.ini` naming a security `group`; on a machine
  joined to an AD domain or to Microsoft Entra, only members of that group may
  run the app (others get an "Access denied" message and the app exits). The
  group is matched by name (`Group` or `DOMAIN\Group`) or by SID, read from the
  user's Windows token. The check is skipped on standalone/non-Windows machines,
  and `deny_on_error` (default `true`) controls fail-closed vs fail-open when
  membership can't be determined.
- MariaDB backend now creates the configured `database` if it doesn't exist yet
  (via `CREATE DATABASE IF NOT EXISTS`), then creates the tables inside it. A
  fresh server no longer needs the schema created by hand — the app bootstraps
  it, given a user with the `CREATE` privilege.

## [0.4.0] - 2026-07-02

### Added
- **Report tab** to save a spending report (summary, and spending by category,
  year, and month, with an optional full list of budget lines) as a **PDF**
  (`fpdf2`), a **Word document** (`python-docx`), or an **audio file**
  (`pyttsx3`, using the voice and speed chosen on the Chart tab). Reachable via
  `Ctrl+4` / `Alt+R` or **File → Save report…**. Each format is offered only
  when its library is installed.

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

[Unreleased]: https://github.com/mediaswing/the-simple-budget/compare/v0.5.2...HEAD
[0.5.2]: https://github.com/mediaswing/the-simple-budget/compare/v0.5.1...v0.5.2
[0.4.0]: https://github.com/mediaswing/the-simple-budget/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/mediaswing/the-simple-budget/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mediaswing/the-simple-budget/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mediaswing/the-simple-budget/releases/tag/v0.1.0
