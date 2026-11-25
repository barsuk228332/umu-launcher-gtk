# AGENTS.md

Agent notes for `umulauncher`: a GTK4/libadwaita launcher for Windows games that
shells out to the system `umu-run`. User-facing docs and troubleshooting live in
`README.md`; read it before changing launch behavior.

## Stack constraints

- **No third-party Python dependencies.** Only stdlib + PyGObject (`gi`) + system
  `umu-run` (optional: `gamescope`, `mangohud`, `winetricks`). Do not add packages
  to `pyproject.toml`; setuptools there only declares the `umulauncher` script.
- Python >= 3.11.
- `umulauncher/core/` must stay GTK-free and importable headless. All GTK code
  lives in `umulauncher/ui/`.
- Entrypoint is `umulauncher/__main__.py`: GUI by default, headless `--run ID`,
  `--list`, `--debug`, `--version`. Exported `.desktop` shortcuts rely on
  `--run ID`, so keep CLI behavior working when touching launch code.

## Commands

```bash
make i18n    # compile po/*.po -> umulauncher/locale/*/LC_MESSAGES/*.mo
make run     # python3 -m umulauncher (GUI; needs a display)
make test    # python3 -m unittest discover -s tests -v
python3 -m unittest discover -s tests -p 'test_runner.py' -v   # single module
python3 -m umulauncher --list                                  # headless check
python3 -m umulauncher --run <id> --debug
make pot     # regenerate po/umulauncher.pot after string changes
make install # no pip: copies package to ~/.local/share/umulauncher/app + wrapper
```

- `tests/` has no `__init__.py`, so `python3 -m unittest tests.test_x` does not
  work. Use `discover` with `-p '<module>.py'` (or `-k`).
- Tests are offline stdlib `unittest`. `test_misc` imports `umulauncher.ui.dialogs`,
  so `gi`/GTK4 must be installed even to run the "core" suite.
- A clean checkout has no `.mo` files (gitignored). Without `make i18n` the UI
  silently falls back to English msgids; run it before GUI testing.

## Conventions and gotchas

- **i18n:** source strings are English msgids in code; Russian lives in
  `po/ru.po` (`po/en.po` is header-only). After adding/changing UI strings run
  `make pot`, update both `.po` files, then `make i18n`. Only `ui/` and
  `core/` files listed in the Makefile's `pot` target are scanned.
- **Paths/config:** constants in `core/config.py` are resolved at import time from
  `XDG_*` and `UMU_FOLDERS_PATH`. Tests patch module attributes
  (`mock.patch.object(desktop.config, "APPLICATIONS_DIR", ...)`) rather than env
  vars. `config.load()`/`get()` return a cached global `Settings`; `config.save()`
  writes atomically with mode 0600.
- **DB:** SQLite at `config.DB_PATH`; every accessor takes an optional `path` for
  tests. Schema is `CREATE TABLE IF NOT EXISTS` + `PRAGMA user_version` only —
  there is no migration framework. Adding a column requires an explicit
  `ALTER TABLE` migration for existing DBs (bump `SCHEMA_VERSION` in `core/db.py`).
- **Launch process:** never pass `os.environ` to `umu-run` directly. Use
  `runner.sanitize_env`/`build_env`, which strip `STEAM_COMPAT_*`,
  `PRESSURE_VESSEL_*`, `SteamAppId`, `LD_PRELOAD` and steam-related
  `LD_LIBRARY_PATH`. Per-game `env` overrides win over all generated variables.
  Subprocesses start with `start_new_session=True` and are stopped by process
  group (SIGTERM, then SIGKILL after a grace period) — preserve this.
- **GTK threading:** run network/disk work in daemon `threading.Thread`s and
  marshal UI updates through `GLib.idle_add`. Never touch widgets from a worker
  thread; existing modules follow this pattern.
- **Prefix safety:** `prefixes.is_safe_prefix` refuses `/`, `$HOME`, `~/Games`,
  relative and too-shallow paths before deletion. Do not weaken these checks.
- **Proton downloads:** resumable `.part` files in `~/.cache/umulauncher/proton-downloads`,
  verified against the published SHA512 and extracted with archive path/symlink
  checks into `config.PROTONS_DIR` (under `$UMU_FOLDERS_PATH` or
  `~/.local/share/umu/compatibilitytools`). Keep checksum verification and
  `_safe_extract` when editing `core/proton_releases.py`.
- New GTK modules must call `gi.require_version("Gtk", "4.0")` and
  `gi.require_version("Adw", "1")` before importing `gi.repository` (see
  `ui/app.py`).

## Packaging

`PKGBUILD` builds an `arch=('any')` binary package from the GitHub tag
`v$pkgver` (not from the working tree). To release a new version: bump
`pkgver` and `__version__`, push the tag, run `updpkgsums`, rebuild with
`makepkg -f`, and attach the `.pkg.tar.zst` to the GitHub release. The package
is unsigned, so install-from-URL needs `pacman -U --nosignature …` or a local
file; document both in README and release notes.
