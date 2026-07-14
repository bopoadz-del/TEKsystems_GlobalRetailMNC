"""CLI entry: python -m app.retailops.packs.load_retail_core_open_v1"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.retailops.db import init_engine, session_scope
from app.retailops.migrations_runner import upgrade_to_head
from app.retailops.packs.retail_core_open_v1.loaders.ingest_text import ingest_all_text
from app.retailops.packs.retail_core_open_v1.loaders.load_structured import (
    load_freshretailnet,
    load_uci_online_retail_ii,
)
from app.retailops.packs.retail_core_open_v1.loaders.summarize_to_rag import generate_summaries
from app.retailops.packs.retail_core_open_v1.registry import load_manifest, release_identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load retail_core_open_v1 content release")
    parser.add_argument(
        "--profile",
        default="pilot",
        choices=["pilot", "mini", "full"],
        help="mini/pilot use committed fixtures; full acquires official sources over HTTPS",
    )
    parser.add_argument("--skip-migrations", action="store_true")
    parser.add_argument(
        "--acquire-uci",
        action="store_true",
        help="Download full UCI zip (implied by --profile full)",
    )
    parser.add_argument(
        "--acquire-fresh",
        action="store_true",
        help="Download FreshRetailNet parquet (implied by --profile full)",
    )
    parser.add_argument(
        "--text-fixtures-dir",
        default="",
        help="Directory with fda_food_code_2022.*, osha_*.*, ftc_*.* for offline text ingest",
    )
    parser.add_argument("--force-text", action="store_true")
    args = parser.parse_args(argv)

    full = args.profile == "full"
    acquire_uci = args.acquire_uci or full
    acquire_fresh = args.acquire_fresh or full

    if not args.skip_migrations:
        upgrade_to_head()
    init_engine()

    fixture_map: dict[str, Path] = {}
    if args.text_fixtures_dir:
        base = Path(args.text_fixtures_dir)
        for sid in ("fda_food_code_2022", "osha_retail_grocery_2009", "ftc_advertising_faqs"):
            for ext in (".txt", ".md", ".html", ".pdf"):
                p = base / f"{sid}{ext}"
                if p.exists():
                    fixture_map[sid] = p
                    break

    # Offline profiles: always use committed mini text fixtures when none provided.
    prefer_network = full and not fixture_map
    if not fixture_map and not prefer_network:
        mini = Path(__file__).resolve().parent / "retail_core_open_v1" / "fixtures_min" / "text"
        if mini.exists():
            for sid in ("fda_food_code_2022", "osha_retail_grocery_2009", "ftc_advertising_faqs"):
                p = mini / f"{sid}.txt"
                if p.exists():
                    fixture_map[sid] = p

    report = {
        "identity": release_identity(),
        "manifest_sources": len(load_manifest()["sources"]),
        "profile": args.profile,
    }
    with session_scope() as session:
        report["text"] = ingest_all_text(
            session,
            fixture_map=fixture_map or None,
            force=args.force_text or full,
            prefer_network=prefer_network,
        )
        report["freshretailnet"] = load_freshretailnet(
            session,
            use_mini_fixture=not acquire_fresh,
            acquire=acquire_fresh,
        )
        report["uci"] = load_uci_online_retail_ii(
            session,
            use_mini_fixture=not acquire_uci,
            acquire=acquire_uci,
        )
        report["summaries"] = generate_summaries(session)

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
