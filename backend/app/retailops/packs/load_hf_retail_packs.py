"""CLI: load Hugging Face retail RAG packs (Bitext, SOPBench, mSOP, rescommons).

Usage:
  PYTHONPATH=. python -m app.retailops.packs.load_hf_retail_packs --pack all --profile mini
  PYTHONPATH=. python -m app.retailops.packs.load_hf_retail_packs --pack cx --profile full --force
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Dict

from app.retailops.db import init_engine, session_scope
from app.retailops.migrations_runner import upgrade_to_head

PACK_LOADERS: Dict[str, Callable[..., Dict[str, Any]]] = {}


def _register() -> None:
    from app.retailops.packs.promo_leaflet_rag_v1.loaders.load import load_pack as load_promo
    from app.retailops.packs.retail_cx_policies_v1.loaders.load import load_pack as load_cx
    from app.retailops.packs.retail_ecom_rag_eval_v1.loaders.load import load_pack as load_eval
    from app.retailops.packs.retail_ops_sops_v1.loaders.load import load_pack as load_sops

    PACK_LOADERS.update(
        {
            "cx": load_cx,
            "sops": load_sops,
            "promo": load_promo,
            "eval": load_eval,
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load HF retail RAG content packs")
    parser.add_argument(
        "--pack",
        default="all",
        choices=["all", "cx", "sops", "promo", "eval"],
        help="Which pack to load",
    )
    parser.add_argument(
        "--profile",
        default="mini",
        choices=["mini", "full", "pilot"],
        help="mini/pilot use committed fixtures; full downloads from Hugging Face",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-migrations", action="store_true")
    args = parser.parse_args(argv)

    profile = "mini" if args.profile == "pilot" else args.profile
    _register()

    if not args.skip_migrations:
        upgrade_to_head()
    init_engine()

    targets = list(PACK_LOADERS) if args.pack == "all" else [args.pack]
    report: Dict[str, Any] = {"profile": profile, "packs": {}}
    for key in targets:
        loader = PACK_LOADERS[key]
        with session_scope() as session:
            report["packs"][key] = loader(session, profile=profile, force=args.force)

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
