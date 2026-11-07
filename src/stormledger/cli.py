"""Command line: refresh snapshots, build the ledger, serve the demo."""

from __future__ import annotations

import argparse

from stormledger.paths import default_curated_dir, repo_root


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="stormledger", description="StormLedger research demonstration")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("refresh", help="Download a new immutable public-data snapshot bundle")
    build = sub.add_parser("build", help="Validate snapshots, transform, train, and write curated artifacts")
    build.add_argument("--out", type=str, default="", help="Curated output directory")

    serve = sub.add_parser("serve", help="Serve the API and the built map")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    demo = sub.add_parser("demo", help="Build from bundled snapshots, then serve")
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    if args.command == "refresh":
        from stormledger.refresh import refresh_snapshots

        manifest = refresh_snapshots(repo_root())
        print(f"Wrote snapshot bundle {manifest['bundle_id']}")
        return
    if args.command in {"build", "demo"}:
        from stormledger.pipeline import run_build

        out = default_curated_dir()
        if args.command == "build" and args.out:
            out = repo_root() / args.out
        metrics = run_build(repo_root(), out)
        test = metrics["test"]
        print(
            f"Published {metrics['published_model']}: "
            f"test MAE linear {test['mae_linear']:.1f}, boosted {test['mae_boosted']:.1f}, "
            f"80% interval coverage {test['interval']['empirical_coverage']:.1%}"
        )
        if args.command == "build":
            return
    if args.command in {"serve", "demo"}:
        import uvicorn

        from stormledger.api import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port)
        return
    parser.error(f"Unknown command {args.command}")


if __name__ == "__main__":
    main()
