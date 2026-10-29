"""对真实 LLM 跑一次风险信号提取，检查后端是否接通。

    set -a; . ./.env; set +a; uv run python scripts/smoke_llm.py
"""

from __future__ import annotations

import logging
import time

from smartlading.llm import BrandContext, SignalExtractor, make_llm
from smartlading.models import SKU, Supplier, SupplierOffer

NEWS = (
    "WASHINGTON - The Office of the U.S. Trade Representative said on Wednesday that, effective 2026-12-01, "
    "duties on cotton knit apparel under HTS 6109.10 will rise from 10% to 25%. "
    "Separately, several textile mills in Ningbo report that power rationing has pushed lead times back by two weeks."
)

CTX = BrandContext(
    brand_id="demo",
    skus=[
        SKU(id="sku_tee", brand_id="demo", name="Organic cotton tee", category="apparel", price=24, unit_platform_fee=7,
            on_hand=1200, hts_code="6109.10.0012", tariff_rate=0.10, demand_template_id="m5_1"),
    ],
    suppliers=[
        Supplier(id="sup_cn", brand_id="demo", name="Ningbo Huafang Textiles", country="CN", lead_time_mean_days=45,
                 lead_time_std_days=8, moq=2000, default_prepay_ratio=0.3, risk_score=0.2),
    ],
    offers=[SupplierOffer(sku_id="sku_tee", supplier_id="sup_cn", unit_cost=4.0, unit_freight=0.6)],
)


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    llm = make_llm()
    print(f"Backend: {type(llm).__name__}  model: {llm.model}")
    started = time.monotonic()
    result = SignalExtractor(llm).extract(NEWS, CTX, source_type="tariff")
    print(f"{time.monotonic() - started:.1f}s, status {result.status}. {result.message or ''}")
    for s in result.signals:
        print(f"- {s.target_type}:{s.target_id} {s.parameter} {s.change_type} {s.change_value} "
              f"p={s.probability} grounded={s.value_grounded} quote={s.quote!r}")
        print(f"  rationale: {s.rationale}")
    for d in result.dropped:
        print(f"- dropped: {d.reason} ({d.change.quote!r})")


if __name__ == "__main__":
    main()
