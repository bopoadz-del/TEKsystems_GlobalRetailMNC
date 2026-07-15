"""Ad-hoc RetailOps oracle runner (stdlib-only, no third-party deps).

There is no formal "oracle" harness in this repository (no tests/oracle,
docs/oracle, judge, or northstar-eval module). What *does* exist is a set of
named, deterministic evaluation fixtures declared on each ActionSpec
(`evaluation_fixtures=[...]` in
`backend/app/retailops/kit/domains/retail/actions.py`) whose literal payloads
live in `backend/app/retailops/kit/domains/retail/fixtures/__init__.py`. They
were never wired to a runner. This script IS that runner: it POSTs each
fixture's exact payload to its action's `/execute` endpoint with
`auto_context=false` (so the deterministic handler sees only the fixture
data, not project retrieval) and asserts the status the handler code
guarantees (`success` for "*_happy"; `dependency_required` for the paired
negative fixture). It also runs the RENDER.md smoke checklist / two-minute
demo as an additional ad-hoc layer (health, root, actions list, RAG /v1/ask,
audit).

Usage:
    python scripts/oracle_smoke.py --base-url https://retailops-3ayp.onrender.com \
        --user u_platform --tenant platform --project prj_prebuilt_retail_core
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

PASS = "PASS"
FAIL = "FAIL"

RESULTS: list[tuple[str, str, str]] = []  # (case, status, detail)


def record(case: str, ok: bool, detail: str) -> None:
    RESULTS.append((case, PASS if ok else FAIL, detail))
    print(f"[{PASS if ok else FAIL}] {case}: {detail}")


def http(
    base_url: str,
    method: str,
    path: str,
    headers: Dict[str, str],
    body: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
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
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = raw
    return status, parsed


# ---------------------------------------------------------------------------
# Fixture payloads copied verbatim from
# backend/app/retailops/kit/domains/retail/fixtures/__init__.py
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

OPERATIONS_BRIEF_NO_RECORDS = {"period": "weekly", "records": []}

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

INVENTORY_RISK_NO_DATA = {"rows": [{"note": "no stock columns here"}]}

PROMOTION_COMPLIANCE_HAPPY = {
    "rules": [
        {"rule_id": "PROMO-1", "requirement": "Spring Promo endcap must display approved signage.", "keywords": ["endcap", "signage"]},
        {"rule_id": "PROMO-2", "requirement": "Promotional price cards must be visible on shelf.", "keywords": ["price", "cards"]},
        {"rule_id": "PROMO-3", "requirement": "Restricted items must not appear in the promotion.", "keywords": ["restricted", "tobacco"]},
    ],
    "evidence": [
        {
            "text": "Store photo review confirms the Spring Promo endcap displays approved signage and "
            "promotional price cards are visible on the shelf.",
            "filename": "store_photos_review.pdf",
            "document_id": "doc_evidence_1",
        }
    ],
    "campaign": "Spring Promo 2024",
}

PROMOTION_COMPLIANCE_NO_RULES = {
    "rules": [],
    "evidence": [{"text": "Store looks compliant.", "filename": "note.txt"}],
}

FIXTURE_CASES = [
    ("operations_brief_happy", "retail.generate_operations_brief", OPERATIONS_BRIEF_HAPPY, "success"),
    ("operations_brief_no_records", "retail.generate_operations_brief", OPERATIONS_BRIEF_NO_RECORDS, "dependency_required"),
    ("inventory_risk_happy", "retail.analyse_inventory_risk", INVENTORY_RISK_HAPPY, "success"),
    ("inventory_risk_no_data", "retail.analyse_inventory_risk", INVENTORY_RISK_NO_DATA, "dependency_required"),
    ("promotion_compliance_happy", "retail.check_promotion_compliance", PROMOTION_COMPLIANCE_HAPPY, "success"),
    ("promotion_compliance_no_rules", "retail.check_promotion_compliance", PROMOTION_COMPLIANCE_NO_RULES, "dependency_required"),
]

EXPECTED_ACTIONS = {
    "retail.generate_operations_brief",
    "retail.analyse_inventory_risk",
    "retail.check_promotion_compliance",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="https://retailops-3ayp.onrender.com")
    ap.add_argument("--user", default="u_platform")
    ap.add_argument("--tenant", default="platform")
    ap.add_argument("--project", default="prj_prebuilt_retail_core")
    args = ap.parse_args()

    headers = {
        "X-User-Id": args.user,
        "X-Tenant-Id": args.tenant,
        "X-Project-Id": args.project,
    }

    print(f"== RetailOps ad-hoc oracle against {args.base_url} "
          f"(user={args.user} tenant={args.tenant} project={args.project}) ==\n")

    # 1. Health
    status, body = http(args.base_url, "GET", "/health", {})
    ok = status == 200 and isinstance(body, dict) and body.get("status") == "ok" and body.get("database") == "ok"
    record("health", ok, f"HTTP {status} body={body}")

    # 2. Root serves business UI shell
    status, body = http(args.base_url, "GET", "/", {})
    record("root_ui_200", status == 200, f"HTTP {status}")

    # 3. Actions discovery
    status, body = http(args.base_url, "GET", "/v1/actions", headers)
    action_ids = set()
    if status == 200 and isinstance(body, dict):
        action_ids = {a.get("action_id") for a in body.get("actions", [])}
    record(
        "actions_discovery",
        status == 200 and EXPECTED_ACTIONS.issubset(action_ids),
        f"HTTP {status} action_ids={sorted(action_ids)}",
    )

    # 4. Fixture-driven oracle cases (the kit's own evaluation_fixtures)
    for case_name, action_id, payload, expected_status in FIXTURE_CASES:
        req_body = {"arguments": payload, "auto_context": False, "confirm": False}
        status, body = http(
            args.base_url, "POST", f"/v1/actions/{action_id}/execute", headers, req_body
        )
        actual_status = body.get("status") if isinstance(body, dict) else None
        ok = status == 200 and actual_status == expected_status
        evidence_n = len(body.get("evidence", []) or []) if isinstance(body, dict) else 0
        record(
            case_name,
            ok,
            f"HTTP {status} expected={expected_status} actual={actual_status} evidence_count={evidence_n}",
        )

    # 5. RAG smoke: /v1/ask should answer with citations when the project has
    #    documents (retail_core_open_v1 platform-prebuilt corpus covers food
    #    safety / advertising topics).
    status, body = http(
        args.base_url,
        "POST",
        "/v1/ask",
        headers,
        {"question": "What are the FTC guidelines for advertising claims?"},
    )
    citations = body.get("citations", []) if isinstance(body, dict) else []
    ok = status == 200 and isinstance(body, dict) and bool(body.get("answer"))
    record(
        "rag_ask_smoke",
        ok,
        f"HTTP {status} route={body.get('route') if isinstance(body, dict) else None} "
        f"citations={len(citations)}",
    )

    # 5b. HF pack RAG prompts (pass when packs loaded; still pass soft on empty
    #     corpus if HTTP 200 with an answer — citations optional).
    hf_prompts = [
        ("rag_bitext_returns", "What is the return policy window for unused items?"),
        (
            "rag_sopbench_warehouse",
            "According to the warehouse package inspection SOP, what should staff do if inbound package damage is found including quarantine?",
        ),
        ("rag_msop_promo", "What is the SunValley soft drinks multipack promotion offer?"),
        ("rag_rescommons_eval", "What is the return window for unused items according to support guidance?"),
    ]
    for case_name, question in hf_prompts:
        status, body = http(
            args.base_url,
            "POST",
            "/v1/ask",
            headers,
            {"question": question},
            timeout=60.0,
        )
        citations = body.get("citations", []) if isinstance(body, dict) else []
        answer = (body.get("answer") or "") if isinstance(body, dict) else ""
        ok = status == 200 and bool(answer)
        record(
            case_name,
            ok,
            f"HTTP {status} citations={len(citations)} answer_len={len(answer)}",
        )

    # 6. Audit persistence: the six execute calls above should be visible.
    status, body = http(args.base_url, "GET", "/v1/audit", headers)
    runs = body.get("runs", []) if isinstance(body, dict) else []
    ok = status == 200 and len(runs) >= len(FIXTURE_CASES)
    record("audit_persistence", ok, f"HTTP {status} run_count={len(runs)}")

    # Summary
    print("\n== Summary ==")
    n_pass = sum(1 for _, s, _ in RESULTS if s == PASS)
    n_fail = sum(1 for _, s, _ in RESULTS if s == FAIL)
    for case, s, detail in RESULTS:
        print(f"  {s:4s} {case}")
    print(f"\n{n_pass}/{len(RESULTS)} passed, {n_fail} failed.")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
