"""RetailOps release gate: six-question regression oracle (stdlib-only).

Complements ``scripts/oracle_smoke.py`` (which proves the kit's own
deterministic action fixtures + basic health/root/actions/audit contract).
``release_gate.py`` is the release-certification regression: a fixed set of
six questions that must keep behaving identically release over release —
three grounded RAG questions (with the reasoner's anti-hijack guarantee that
any *question* stays on RAG, never fabricated into an action), two direct
action-contract executions (using the kit's own guaranteed-success
``evaluation_fixtures`` payloads, so they do not depend on any particular
project's document corpus), and one unsupported-command rejection.

The three RAG questions are answered from the platform-prebuilt corpus
(``retail_core_open_v1`` + the four Hugging Face retail RAG packs) that is
loaded into the working principal's project by
``load_retail_core_open_v1`` / ``load_hf_retail_packs``:

  - stock discrepancy escalation -> amazon/sop-bench order-fulfilment /
    warehouse-inspection SOPs (retail_ops_sops_v1)
  - chilled supplier promo       -> "Harbour Fresh — chilled dairy" leaflet
    offer (promo_leaflet_rag_v1, mSOP-765k)
  - return window                -> Bitext return-policy FAQ
    (retail_cx_policies_v1) / rescommons grounded snippet
    (retail_ecom_rag_eval_v1)

Every assertion is a hard, exit-code-affecting assertion: this script exits
non-zero (and prints a PASS/FAIL table) if *any* of the six regression cases
fails its contract, so it can gate a release the same way CI gates a PR.

Usage:
    python scripts/release_gate.py --base-url https://retailops-3ayp.onrender.com \
        --user u_platform --tenant platform --project prj_prebuilt_retail_core \
        [--api-key <key>]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

PASS = "PASS"
FAIL = "FAIL"


def http(
    base_url: str,
    method: str,
    path: str,
    headers: Dict[str, str],
    body: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
) -> Tuple[int, Any]:
    url = base_url.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        status = e.code
    except urllib.error.URLError as e:
        return 0, {"error": str(e)}
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = raw
    return status, parsed


# ---------------------------------------------------------------------------
# Fixture payloads (verbatim from
# backend/app/retailops/kit/domains/retail/fixtures/__init__.py, same ones
# scripts/oracle_smoke.py exercises) — deterministic, corpus-independent.
# ---------------------------------------------------------------------------

OPERATIONS_BRIEF_HAPPY = {
    "period": "daily",
    "store": "Flagship Store A",
    "records": [
        {
            "text": "Incident report: A customer slipped near the chilled aisle at 09:14. "
            "First aid administered. Wet-floor signage was missing.",
            "filename": "incident_2024_03_02.pdf",
            "document_id": "doc_incident_1",
            "page": 1,
        },
        {
            "text": "Supplier notice: Chilled dairy shipment from Harbour Fresh Dairy Co. "
            "delayed 24h due to cold-chain inspection. Affects SKUs DAIRY-1001..1009.",
            "filename": "supplier_notice_dairy.pdf",
            "document_id": "doc_supplier_1",
        },
        {
            "text": "Inventory record: SKU BEV-2201 on-hand 4 units below reorder point of 20; "
            "possible stock discrepancy flagged during morning count.",
            "filename": "inventory_note.txt",
            "document_id": "doc_inv_1",
        },
        {
            "text": "Merchandising instruction: Endcap display for the Spring Promo must "
            "show approved signage and price cards by store open.",
            "filename": "promo_display.md",
            "document_id": "doc_promo_1",
        },
    ],
}

INVENTORY_RISK_HAPPY = {
    "rows": [
        {"SKU": "BEV-2201", "Product": "Sparkling Water 500ml", "On Hand": 4, "Reorder Point": 20, "Avg Daily Sales": 6, "Store": "Flagship Store A"},
        {"SKU": "SNK-3310", "Product": "Roasted Almonds 200g", "On Hand": 900, "Reorder Point": 50, "Avg Daily Sales": 3, "Store": "Flagship Store A"},
        {"SKU": "DAIRY-1001", "Product": "Full Cream Milk 1L", "on_hand": 120, "reorder_point": 40, "average_daily_sales": 30, "store": "Flagship Store A"},
        {"sku": "HOME-7788", "product_name": "Scented Candle", "on_hand": 60, "average_daily_sales": 0, "store": "Flagship Store A"},
        {"sku": "TOY-5501", "product_name": "Building Blocks", "on_hand": -3, "reorder_point": 10, "average_daily_sales": 2, "last_count": 25, "current_count": 40},
    ],
    "records": [
        {"text": "Daily inventory export for Flagship Store A", "filename": "inventory_global.csv", "document_id": "doc_inv_csv"}
    ],
}


def main() -> int:
    ap = argparse.ArgumentParser(description="RetailOps release gate (six-question regression)")
    ap.add_argument("--base-url", default="https://retailops-3ayp.onrender.com")
    ap.add_argument("--user", default="u_platform")
    ap.add_argument("--tenant", default="platform")
    ap.add_argument("--project", default="prj_prebuilt_retail_core")
    ap.add_argument("--api-key", default=None, help="Sent as X-API-Key when RETAILOPS_API_KEY is configured server-side")
    args = ap.parse_args()

    headers = {
        "X-User-Id": args.user,
        "X-Tenant-Id": args.tenant,
        "X-Project-Id": args.project,
    }
    if args.api_key:
        headers["X-API-Key"] = args.api_key

    print(
        f"== RetailOps release gate against {args.base_url} "
        f"(user={args.user} tenant={args.tenant} project={args.project}) ==\n"
    )

    results: List[Tuple[str, str, str]] = []

    def check(case: str, ok: bool, detail: str) -> None:
        results.append((case, PASS if ok else FAIL, detail))
        print(f"[{PASS if ok else FAIL}] {case}: {detail}")

    def ask(question: str) -> Tuple[int, Any]:
        return http(args.base_url, "POST", "/v1/ask", headers, {"question": question})

    def execute(action_id: str, arguments: Dict[str, Any]) -> Tuple[int, Any]:
        return http(
            args.base_url,
            "POST",
            f"/v1/actions/{action_id}/execute",
            headers,
            {"arguments": arguments, "auto_context": False, "confirm": False},
        )

    # 1. Stock discrepancy escalation — grounded RAG, no action hijack.
    status, body = ask("What is the escalation process for a stock discrepancy?")
    route = body.get("route") if isinstance(body, dict) else None
    answer = (body.get("answer") or "") if isinstance(body, dict) else ""
    citations = body.get("citations", []) if isinstance(body, dict) else []
    check(
        "stock_discrepancy_escalation_rag",
        status == 200 and route == "rag" and bool(answer) and len(citations) >= 1,
        f"HTTP {status} route={route} answer_len={len(answer)} citations={len(citations)}",
    )

    # 2. Ops brief — direct action-contract execution (fixture payload).
    status, body = execute("retail.generate_operations_brief", OPERATIONS_BRIEF_HAPPY)
    action_status = body.get("status") if isinstance(body, dict) else None
    check(
        "ops_brief_action",
        status == 200 and action_status == "success",
        f"HTTP {status} status={action_status}",
    )

    # 3. Chilled supplier — grounded RAG on the "Harbour Fresh chilled dairy"
    #    promo leaflet pack.
    status, body = ask("What is the offer price on the Harbour Fresh chilled dairy leaflet promotion?")
    route = body.get("route") if isinstance(body, dict) else None
    answer = (body.get("answer") or "") if isinstance(body, dict) else ""
    citations = body.get("citations", []) if isinstance(body, dict) else []
    excerpts = " ".join((c.get("excerpt") or "") for c in citations if isinstance(c, dict)).lower()
    mentions_chilled = "chilled" in excerpts or "harbour fresh" in excerpts
    check(
        "chilled_supplier_rag",
        status == 200 and route == "rag" and bool(answer) and len(citations) >= 1 and mentions_chilled,
        f"HTTP {status} route={route} citations={len(citations)} mentions_chilled={mentions_chilled}",
    )

    # 4. Inventory risk — direct action-contract execution (fixture payload).
    status, body = execute("retail.analyse_inventory_risk", INVENTORY_RISK_HAPPY)
    action_status = body.get("status") if isinstance(body, dict) else None
    check(
        "inventory_risk_action",
        status == 200 and action_status == "success",
        f"HTTP {status} status={action_status}",
    )

    # 5. Unknown action — must be rejected as unsupported, never fabricated.
    status, body = ask("Please book me a flight to the moon.")
    route = body.get("route") if isinstance(body, dict) else None
    check(
        "unknown_action_unsupported",
        status == 200 and route == "unsupported",
        f"HTTP {status} route={route}",
    )

    # 6. Return window — grounded RAG anti-hijack: a factual policy question
    #    must stay on RAG, never get hijacked into an action (e.g. a write).
    status, body = ask("What is the return window for unused items?")
    route = body.get("route") if isinstance(body, dict) else None
    answer = (body.get("answer") or "") if isinstance(body, dict) else ""
    citations = body.get("citations", []) if isinstance(body, dict) else []
    action_result = body.get("action_result") if isinstance(body, dict) else None
    check(
        "return_window_rag_anti_hijack",
        status == 200 and route == "rag" and action_result is None and bool(answer) and len(citations) >= 1,
        f"HTTP {status} route={route} action_result={action_result} citations={len(citations)}",
    )

    # Summary table.
    print("\n== Release gate summary ==")
    print(f"{'Case':<32} {'Result':<6}")
    print("-" * 40)
    n_pass = 0
    for case, status_str, _detail in results:
        print(f"{case:<32} {status_str:<6}")
        if status_str == PASS:
            n_pass += 1
    n_fail = len(results) - n_pass
    print("-" * 40)
    print(f"{n_pass}/{len(results)} passed, {n_fail} failed.")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
