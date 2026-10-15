#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script gửi thầy xin ý kiến quyết định chiến lược tích hợp Snowplow vào CDP.
Chạy: .venv\Scripts\python.exe docs/ask_professor_strategy.py
Output: file docs/ask_professor_strategy.txt
"""

STRATEGY_A = """
=== CHIEN LUOC A — THAY THE HOAN TOAN (Full Migration) ===

Y tuong:    CDP Demo chi lam UI prototype, backend thay hoan toan bang
            Snowplow (Collector -> Enrich -> Warehouse -> BI).

Thay the:   catalog.js          -> Snowplow JS Tracker
            Demo API            -> Snowplow Collector (Kinesis/Kafka)
            CSV/Parquet        -> Snowflake / BigQuery / Redshift
            dashboard.js        -> Looker / Tableau / Sigma + dbt

Effort:      Cao (8-16 tuan) — infra + engineering + data modeling
Pros:        Full Snowplow; khong co vendor lock-in; production-ready
Cons:        Ton nhieu resource; risk cao; CDP Demo hien tai bi bo
"""

STRATEGY_B = """
=== CHIEN LUOC B — BO SUNG TUNG TANG (Layered Addition) ===

Y tuong:    Giu nguyen CDP Demo, bo sung tung tang Snowplow ben duoi.

Tang 1:      Iglu Schema Registry (2-3 tuan) — validate event schema
Tang 2:      Stream Enrichment (3-4 tuan) — geo, UA, campaign parsing
Tang 3:      Warehouse + dbt models (4-6 tuan) — Snowflake + data models
Tang 4:      Identity Resolution (4-8 tuan) — cross-device stitching

Effort:      Trung binh–Cao (13-21 tuan tong)
Pros:        Moi tang doc lap; deliverable ro rang; hoc tung buoc
Cons:        Kien truc phuc tap dan (2 he thong song song); cham hon A
"""

STRATEGY_C = """
=== CHIEN LUOC C — CDP DEMO + SNOWPLOW SONG SONG (Side-by-Side) ===

Y tuong:    CDP Demo giu nguyen cho demo/education; trien khai Snowplow
            that su cho production (hoac du an khac).

CDP Demo:    Chay nhu cu — chi de show persona concept + training team
Snowplow:    Thu thap event tu ung dung production (neu co)

Effort:      Trung binh (4-8 tuan cho Snowplow production)
Pros:        CDP Demo bao toan; Snowplow khong anh huong demo hien tai
Cons:        Hai codebase rieng biet can bao tri; resource chia doi
"""

QUESTION = """
=== CAU HOI CHO THAY ===

Hien tai project CDP dang o giai doan prototype/demo voi:
  - 1 Web SPA (HTML/JS) + 1 FastAPI + CSV file storage + Dashboard (dang chay tot)
  - 16 event types, 4 user personas (Lina/Minh/Hoa/Quang), 250 san pham
  - Kien truc hien tai tuong duong "mini-Snowplow" — da co: collection,
    storage, quarantine, idempotency, manifest checksum
  - Gioi han so voi Snowplow that: khong co Iglu (schema registry), khong co
    enrichment (geo/UA/campaign), khong co warehouse loader, khong co dbt models

Thay kuyen nen di theo huong nao:

  (A) Thay the hoan toan — nhanh dat production-ready, nhung bo CDP Demo
  (B) Bo sung tung tang — cham ma chắc, hoc tung layer Snowplow
  (C) Song song — bao toan CDP Demo, tach Snowplow cho production

Ngoai ra, thay co de xuat chien luoc nao khac khong?
"""


def main():
    content = """
================================================================================
BAO CAO XIN Y KIEN THAY — CHIEN LUOC TICH HOP SNOWPLOW VAO DU AN CDP
================================================================================

Gui Thay,

Em dang lam du an Customer Data Platform (CDP) va can thay gop y ve chien
luoc tich hop Snowplow Analytics vao kien truc hien tai.

--- BOI CANH ---
CDP Demo hien tai: Web SPA + FastAPI + CSV storage + Dashboard (dang chay tot)
Event model: 16 event types, 4 personas (Lina/Minh/Hoa/Quang), 250 san pham
Kien truc hien tai tuong duong "mini-Snowplow" — da co: collection, storage,
quarantine, idempotency, manifest checksum
Gioi han so voi Snowplow that: khong co Iglu (schema registry), khong co
enrichment (geo/UA/campaign), khong co warehouse loader, khong co dbt models

--- 3 CHIEN LUOC DE XUAT ---

{strA}
{strB}
{strC}

{question}

================================================================================
""".format(strA=STRATEGY_A, strB=STRATEGY_B, strC=STRATEGY_C, question=QUESTION)

    # Luu ra file de copy-paste
    out_file = "docs/ask_professor_strategy.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(content)
    print("Da luu:", out_file)


if __name__ == "__main__":
    main()
