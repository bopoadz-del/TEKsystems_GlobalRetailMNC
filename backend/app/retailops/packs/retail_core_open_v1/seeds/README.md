# Official-source seeds

Committed artifacts used only when live HTTPS acquisition fails
(e.g. FDA abuse-detection blocking cloud egress IPs).

| File | Provenance |
|------|------------|
| `fda_food_code_2022.pdf` | FDA Food Code 2022 PDF (`media/164194`), acquired via Internet Archive Wayback `if_` mirror of the official FDA media URL when direct `fda.gov` returned abuse-detection HTML. SHA-256 recorded at ingest time. |
| `fda_food_code_2022.pages.jsonl` | Page-extracted text from the same PDF (NUL-stripped) for memory-safe streaming ingest on starter jobs. One JSON object per page: `{"page":N,"text":"..."}`. |
| `ftc_advertising_faqs.txt` | Cleaned main-content text extracted from the official FTC Advertising FAQs HTML page (nav/chrome removed, capped). |

Network acquisition is still preferred for OSHA/FTC; FDA ingest typically streams the pages JSONL derived from the official PDF seed.
