"""Entry point: GUI by default, headless ``--run`` for .desktop shortcuts."""

from __future__ import annotations

import argparse
import sys
import time


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="umulauncher",
        description="GTK4 launcher for Windows games on Linux powered by umu-launcher.",
    )
    parser.add_argument("--run", type=int, metavar="ID", help="run a game by its library id, without opening the UI")
    parser.add_argument("--list", action="store_true", help="print the library and exit")
    parser.add_argument("--debug", action="store_true", help="force UMU_LOG=1 output")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    return parser


def _run_cli(game_id: int, debug: bool) -> int:
    from .core import db, runner

    game = db.get_game(game_id)
    if game is None:
        print(f"umulauncher: no game with id {game_id}", file=sys.stderr)
        return 2

    plan = runner.LaunchPlan.from_game(game)
    if debug:
        plan.debug = True
    if not game.prefix_path:
        game.prefix_path = plan.prefix
        db.update_game(game)

    started = time.monotonic()
    try:
        code = runner.run_blocking(plan, echo=True)
    except runner.LaunchError as exc:
        print(f"umulauncher: {exc}", file=sys.stderr)
        return 3
    db.add_playtime(int(game.id), int(time.monotonic() - started))
    return code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from . import __version__
    from .core import config, db, i18n

    if args.version:
        print(f"umulauncher {__version__}")
        return 0

    config.ensure_dirs()
    settings = config.load()
    i18n.setup(settings.language)
    db.init()

    if args.list:
        games = db.list_games()
        if not games:
            print("umulauncher: library is empty", file=sys.stderr)
            return 1
        for game in games:
            print(f"{game.id}\t{game.title}\t{game.game_id}\t{game.proton_path or 'UMU-Proton'}")
        return 0

    if args.run is not None:
        return _run_cli(args.run, args.debug)

    from .ui.app import App

    app = App()
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
