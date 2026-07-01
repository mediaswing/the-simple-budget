# the-simple-budget

A personal budget tracker, useful for logging what you spend and seeing where
your money goes.

`budget_app.py` is a self-contained Tkinter desktop app. It stores data in its
own SQLite database (`budget.db`, created automatically on first run) and draws
its chart directly on a Tk canvas, so the core app needs nothing beyond a
standard Python install with Tk.

## Features

- **Data tab** — add, edit, and delete budget lines (store, price, date,
  category). Spending categories are seeded on first run.
- **Chart tab** — a column graph of total spend (GBP), grouped by **category**,
  **year**, or **month**.
- **Accessibility** — full keyboard control, mnemonics, a menu bar, and a
  focusable chart.
- **Read chart aloud** — the chart can be spoken as plain-language text via
  [`pyttsx3`](https://pypi.org/project/pyttsx3/) for visually impaired users,
  with a live on-screen transcript, a **voice picker**, and a **speed slider**.

## Requirements

- Python 3 with Tk (bundled with most Python installs; `python3 -m tkinter`
  should open a test window).
- Optional: `pyttsx3` for the read-aloud feature.

```sh
pip install pyttsx3
```

If `pyttsx3` is not installed the app still runs normally — the speech controls
are disabled and the transcript explains how to enable them.

## Running

```sh
python3 budget_app.py
```

## Standalone binaries

Prebuilt Windows, macOS, and Linux binaries are produced by the
`Build binaries` GitHub Actions workflow (see `.github/workflows/build.yml`) and
attached to each tagged release. To build one yourself for the current OS:

```sh
pip install pyinstaller pyttsx3
pyinstaller --noconfirm --clean TheSimpleBudget.spec
```

The result appears in `dist/` (a `TheSimpleBudget.app` on macOS, a
`TheSimpleBudget/` folder containing the executable on Windows/Linux).
PyInstaller does **not** cross-compile — each platform's binary must be built on
that platform (which is what the CI workflow does).

> **Linux note:** the read-aloud feature uses eSpeak, so Linux users need it
> installed (`sudo apt-get install espeak`).

## Keyboard shortcuts

### Navigation
| Shortcut | Action |
| --- | --- |
| `Ctrl+1` / `Alt+D` | Data tab |
| `Ctrl+2` / `Alt+C` | Chart tab |
| `Ctrl+Tab` | Next tab |
| `Tab` / `Shift+Tab` | Move between controls |

### Editing (Data tab)
| Shortcut | Action |
| --- | --- |
| `Ctrl+N` | New line (clear the form and focus the first field) |
| `Ctrl+S` / `Enter` | Add or update the line |
| `Del` | Delete the selected line |
| `Esc` | Clear the form |

### Accessibility (Chart tab)
| Shortcut | Action |
| --- | --- |
| `Ctrl+T` | Read the chart aloud |
| `Esc` | Stop reading |
| `Ctrl+R` | Refresh the chart |

Press `F1` at any time for the in-app shortcut reference. The voice and speaking
speed used for read-aloud can be changed from the controls on the Chart tab.
