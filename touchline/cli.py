"""`touchline <command>`: operator commands. Run `touchline --help` for the list."""

import argparse
import json

from touchline import scheduler, strategy
from touchline.config import config, setup_logging
from touchline.db import connect, now, set_setting
from touchline.jobs import ingest, modelling, odds
from touchline.leagues import BY_CODE, LEAGUES
from touchline.model import backtest
from touchline.sources import understat

PROMOTION_MIN_PROSPECTIVE = 200


def _leagues(code: str | None) -> list[str]:
    return [code] if code else [lg.code for lg in LEAGUES]


def backfill(args) -> None:
    at = now()
    current = understat.season_start(at)
    seasons = range(current - args.seasons + 1, current + 1)
    for code in _leagues(args.league):
        print(f"{code}: {ingest.sync_league(code, seasons, at)} fixtures")
        if args.rosters:
            while done := ingest.hydrate_rosters(200):
                print(f"{code}: +{done} rosters")
        print(f"{code}: fitted {modelling.fit_league(code, at)}")
    print(f"predicted {modelling.predict_upcoming(at)} upcoming fixtures")


def run_backtest(args) -> None:
    at = now()
    with connect() as conn:
        results = modelling.load_results(conn, args.league, at)
        builder = modelling.load_builder(conn, args.league, at)
    if args.xi:
        report = backtest.compare(results, builder, retrain_days=args.retrain_days)
        with connect() as conn:
            set_setting(conn, f"backtest:{args.league}", {**report, "at": at})
            set_setting(conn, f"xi_config:{args.league}", report["config"])
        rows = {"baseline": report["baseline"], "xi": report["candidate"]}
        print(f"historical_ok={report['historical_ok']} config={report['config']}")
    else:
        rows = {
            "baseline": backtest.summary(
                backtest.walk_forward(results, retrain_days=args.retrain_days)
            )
        }
    for name, s in rows.items():
        if s["fixtures"]:
            print(
                f"{name:9} fixtures={s['fixtures']} accuracy={s['accuracy']:.3f} "
                f"log_loss={s['log_loss']:.4f} brier={s['brier']:.4f}"
            )
        else:
            print(f"{name:9} no evaluable fixtures")


def promote(args) -> None:
    with connect() as conn:
        if args.model == "xi-v2" and not args.force:
            report = conn.execute(
                "SELECT value FROM settings WHERE key=?", (f"backtest:{args.league}",)
            ).fetchone()
            prospective = conn.execute(
                "SELECT COUNT(DISTINCT p.match_id) FROM predictions p JOIN matches m ON "
                "m.id=p.match_id WHERE m.league=? AND p.version='xi-v2' AND p.with_lineup=1",
                (args.league,),
            ).fetchone()[0]
            ok = report and json.loads(report[0])["historical_ok"]
            if not ok or prospective < PROMOTION_MIN_PROSPECTIVE:
                raise SystemExit(
                    f"not eligible: historical_ok={bool(ok)} prospective="
                    f"{prospective}/{PROMOTION_MIN_PROSPECTIVE} (use --force)"
                )
        strategy.save(conn, args.league, active_model=args.model)
    print(f"{args.league} now uses {args.model}")


def refresh_odds(args) -> None:
    print(f"stored {odds.refresh_odds(_leagues(args.league), now())} events")


def reset(args) -> None:
    if not args.confirm:
        raise SystemExit("refusing without --confirm (deletes all data and the paper ledger)")
    path = config().db_path
    for suffix in ("", "-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
    print(f"deleted {path}")


def main(argv=None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(prog="touchline")
    sub = parser.add_subparsers(dest="command", required=True)
    league_arg = {"choices": sorted(BY_CODE), "help": "league code (default: all)"}

    p = sub.add_parser("backfill", help="import seasons of results, fit models")
    p.add_argument("--league", **league_arg)
    p.add_argument("--seasons", type=int, default=4)
    p.add_argument("--rosters", action="store_true", help="also fetch player rosters (slow)")
    p.set_defaults(fn=backfill)

    p = sub.add_parser("backtest", help="walk-forward log loss / Brier")
    p.add_argument("--league", required=True, choices=sorted(BY_CODE))
    p.add_argument("--xi", action="store_true", help="compare the XI model with the baseline")
    p.add_argument("--retrain-days", type=int, default=7)
    p.set_defaults(fn=run_backtest)

    p = sub.add_parser("promote", help="switch a league's active model")
    p.add_argument("--league", required=True, choices=sorted(BY_CODE))
    p.add_argument("--model", required=True, choices=strategy.MODEL_VERSIONS)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=promote)

    p = sub.add_parser("odds", help="refresh odds now (1 credit per league)")
    p.add_argument("--league", **league_arg)
    p.set_defaults(fn=refresh_odds)

    sub.add_parser("tick", help="run one scheduler cycle").set_defaults(
        fn=lambda a: print(json.dumps(scheduler.tick(), indent=1, default=str))
    )

    p = sub.add_parser("reset", help="delete the database")
    p.add_argument("--confirm", action="store_true")
    p.set_defaults(fn=reset)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
