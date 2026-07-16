"""Generates the PBIR pages + visuals of the ERP Command Center report.

The report is authored as code: every page.json and visual.json below is
emitted from compact specs, so layout changes are one edit + one rerun away
and the whole report stays reviewable in git diffs.

Usage:  python powerbi/tools/generate_report_pages.py
"""

from __future__ import annotations

import json
import os

SCHEMA_VISUAL = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.0.0/schema.json"
SCHEMA_PAGE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json"

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "ERP Command Center.Report", "definition", "pages")

MEASURES = "_Measures"


def measure(entity: str, prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def column(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def projection(field: dict, entity: str, prop: str) -> dict:
    return {"field": field, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}


def title_props(text: str, font_size_pt: int = 20) -> dict:
    return {
        "visualType": "textbox",
        "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [
            {"value": text, "textStyle": {"fontSize": f"{font_size_pt}pt",
                                          "fontWeight": "bold"}}]}]}}]},
        "drillFilterOtherVisuals": True,
    }


def literal(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def vc_title(text: str | None, show: bool = True) -> dict:
    props: dict = {"show": literal("true" if show else "false")}
    if text is not None:
        props["text"] = literal(f"'{text}'")
    return {"title": [{"properties": props}]}


def visual(name: str, x: float, y: float, w: float, h: float, z: int,
           visual_obj: dict, filters: list | None = None) -> dict:
    out = {
        "$schema": SCHEMA_VISUAL,
        "name": name,
        "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
        "visual": visual_obj,
    }
    if filters:
        out["filterConfig"] = {"filters": filters}
    return out


def card(measure_prop: str, title: str | None = None) -> dict:
    return {
        "visualType": "cardVisual",
        "query": {"queryState": {"Data": {"projections": [
            projection(measure(MEASURES, measure_prop), MEASURES, measure_prop)]}}},
        "visualContainerObjects": vc_title(title) if title else {},
        "drillFilterOtherVisuals": True,
    }


def line_chart(cat_entity: str, cat_prop: str, y_props: list[str], title: str) -> dict:
    return {
        "visualType": "lineChart",
        "query": {"queryState": {
            "Category": {"projections": [
                dict(projection(column(cat_entity, cat_prop), cat_entity, cat_prop), active=True)]},
            "Y": {"projections": [
                projection(measure(MEASURES, p), MEASURES, p) for p in y_props]},
        }},
        "visualContainerObjects": vc_title(title),
        "drillFilterOtherVisuals": True,
    }


def bar_chart(cat_entity: str, cat_prop: str, y_prop: str, title: str,
              chart_type: str = "barChart", sort_by_value: bool = True) -> dict:
    query: dict = {
        "queryState": {
            "Category": {"projections": [
                dict(projection(column(cat_entity, cat_prop), cat_entity, cat_prop), active=True)]},
            "Y": {"projections": [projection(measure(MEASURES, y_prop), MEASURES, y_prop)]},
        },
    }
    if sort_by_value:   # rank by magnitude; otherwise the category's own sort order (e.g. bucket order) holds
        query["sortDefinition"] = {
            "sort": [{"field": measure(MEASURES, y_prop), "direction": "Descending"}],
            "isDefaultSort": True,
        }
    return {
        "visualType": chart_type,
        "query": query,
        "visualContainerObjects": vc_title(title),
        "drillFilterOtherVisuals": True,
    }


def table(fields: list[tuple[str, str, str]], title: str) -> dict:
    """fields: list of (kind, entity, prop) with kind in {column, measure}."""
    projections = []
    for kind, entity, prop in fields:
        f = column(entity, prop) if kind == "column" else measure(entity, prop)
        projections.append(projection(f, entity, prop))
    return {
        "visualType": "tableEx",
        "query": {"queryState": {"Values": {"projections": projections}}},
        "visualContainerObjects": vc_title(title),
        "drillFilterOtherVisuals": True,
    }


def decomposition_tree(analyze_prop: str, explain_by: list[tuple[str, str]], title: str) -> dict:
    return {
        "visualType": "decompositionTreeVisual",
        "query": {"queryState": {
            "Analyze": {"projections": [projection(measure(MEASURES, analyze_prop), MEASURES, analyze_prop)]},
            "ExplainBy": {"projections": [
                projection(column(e, p), e, p) for e, p in explain_by]},
        }},
        "visualContainerObjects": vc_title(title),
        "drillFilterOtherVisuals": True,
    }


def page(name: str, display: str, visuals: dict[str, dict]) -> None:
    pdir = os.path.join(ROOT, name)
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, "page.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({
            "$schema": SCHEMA_PAGE,
            "name": name,
            "displayName": display,
            "displayOption": "FitToPage",
            "height": 720,
            "width": 1280,
        }, f, indent=2)
        f.write("\n")
    for vname, vjson in visuals.items():
        vdir = os.path.join(pdir, "visuals", vname)
        os.makedirs(vdir, exist_ok=True)
        with open(os.path.join(vdir, "visual.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(vjson, f, indent=2)
            f.write("\n")


def main() -> None:
    page("overview", "Overview", {
        "title_box": visual("title_box", 24, 16, 900, 56, 1000,
                            title_props("ERP Command Center — weekly operations, with receipts")),
        "card_revenue": visual("card_revenue", 24, 92, 296, 144, 2000,
                               card("Revenue (This Week)", "Revenue — last full week")),
        "card_orders": visual("card_orders", 336, 92, 296, 144, 2100,
                              card("Orders (This Week)", "Orders — last full week")),
        "card_ontime": visual("card_ontime", 648, 92, 296, 144, 2200,
                              card("On-Time % (This Week)", "On-time shipping — last full week")),
        "card_alerts": visual("card_alerts", 960, 92, 296, 144, 2300,
                              card("Alert Count", "Signals firing now")),
        "trend_revenue": visual("trend_revenue", 24, 252, 608, 292, 3000,
                                line_chart("DimWeek", "Week", ["Revenue"], "Weekly revenue")),
        "trend_ontime": visual("trend_ontime", 648, 252, 608, 292, 3100,
                               line_chart("DimWeek", "Week", ["On-Time %"], "On-time shipping %")),
        "card_verdict": visual("card_verdict", 24, 560, 1232, 140, 4000,
                               card("Weekly Verdict", "What changed — plain language")),
    })

    page("drivers", "Drivers", {
        "title_box": visual("title_box", 24, 16, 900, 56, 1000,
                            title_props("Drivers — where the move concentrates")),
        "decomp_revenue": visual("decomp_revenue", 24, 92, 736, 588, 2000,
                                 decomposition_tree("Revenue",
                                                    [("FactOrders", "Region"),
                                                     ("FactOrders", "Customer"),
                                                     ("FactOrders", "Status")],
                                                    "Decompose revenue by region, customer, status")),
        "bar_region": visual("bar_region", 776, 92, 480, 280, 3000,
                             bar_chart("FactOrders", "Region", "Revenue", "Revenue by region")),
        "table_customers": visual("table_customers", 776, 388, 480, 292, 4000,
                                  table([("column", "FactOrders", "Customer"),
                                         ("measure", MEASURES, "Revenue (This Week)"),
                                         ("measure", MEASURES, "Revenue WoW %"),
                                         ("measure", MEASURES, "Customer Revenue Share"),
                                         ("measure", MEASURES, "Revenue Sparkline")],
                                        "Customers — share, WoW and 13-week trend")),
    })

    page("stock", "Stock", {
        "title_box": visual("title_box", 24, 16, 900, 56, 1000,
                            title_props("Stock — cover before it becomes a stockout")),
        "table_items": visual("table_items", 24, 92, 672, 588, 2000,
                              table([("column", "DimItem", "Item Code"),
                                     ("column", "DimItem", "Stock Qty"),
                                     ("column", "DimItem", "Avg Weekly Demand"),
                                     ("column", "DimItem", "Cover Weeks"),
                                     ("measure", MEASURES, "Cover Bar")],
                                    "Items — stock, demand and cover")),
        "card_lowcover": visual("card_lowcover", 712, 92, 544, 140, 3000,
                                card("Low Cover Items", "Items below the cover threshold")),
        "bar_qty_item": visual("bar_qty_item", 712, 248, 544, 432, 4000,
                               bar_chart("DimItem", "Item Code", "Qty", "Ordered quantity by item")),
    })

    page("trust", "Trust", {
        "title_box": visual("title_box", 24, 16, 1100, 56, 1000,
                            title_props("Trust — the dashboard shows its SQL receipts")),
        "card_recon": visual("card_recon", 24, 92, 290, 140, 2000,
                             card("Reconciliation Mismatches", "Source mismatches")),
        "card_dq": visual("card_dq", 330, 92, 290, 140, 2100,
                          card("DQ Issues", "Data-quality issues")),
        "card_audit": visual("card_audit", 636, 92, 290, 140, 2200,
                             card("Audited Statements", "SQL statements executed")),
        "card_trust": visual("card_trust", 942, 92, 314, 140, 2300,
                             card("Trust Statement", "Verdict")),
        "table_recon": visual("table_recon", 24, 248, 500, 200, 3000,
                              table([("column", "MetaReconciliation", "Entity"),
                                     ("column", "MetaReconciliation", "Fetched"),
                                     ("column", "MetaReconciliation", "Source Count"),
                                     ("column", "MetaReconciliation", "Match")],
                                    "Source reconciliation")),
        "table_dq": visual("table_dq", 24, 464, 500, 216, 4000,
                           table([("column", "MetaDataQuality", "Issue")],
                                 "Data-quality gate findings")),
        "table_audit": visual("table_audit", 540, 248, 716, 432, 5000,
                              table([("column", "MetaAuditTrail", "Label"),
                                     ("column", "MetaAuditTrail", "Rows"),
                                     ("column", "MetaAuditTrail", "Seconds"),
                                     ("column", "MetaAuditTrail", "SQL")],
                                    "SQL audit trail — every statement executed")),
    })

    page("aging", "Aging", {
        "title_box": visual("title_box", 24, 16, 1000, 56, 1000,
                            title_props("Receivables aging — chase the oldest balances first")),
        "card_total_ar": visual("card_total_ar", 24, 92, 296, 140, 2000,
                                card("Total AR", "Open receivables")),
        "card_overdue_pct": visual("card_overdue_pct", 336, 92, 296, 140, 2100,
                                   card("Overdue %", "Share past due")),
        "card_over90": visual("card_over90", 648, 92, 296, 140, 2200,
                              card("AR 90+ Days", "Hardest to collect")),
        "bar_buckets": visual("bar_buckets", 24, 252, 608, 428, 3000,
                              bar_chart("FactReceivables", "Aging Bucket", "Total AR",
                                        "Open receivables by age", chart_type="columnChart",
                                        sort_by_value=False)),
        "bar_overdue_cust": visual("bar_overdue_cust", 648, 252, 608, 428, 4000,
                                   bar_chart("FactReceivables", "Customer", "Overdue AR",
                                             "Overdue by customer — worst first")),
    })

    n_pages = 5
    n_visuals = sum(len(os.listdir(os.path.join(ROOT, p, "visuals")))
                    for p in ("overview", "drivers", "stock", "aging", "trust"))
    print(f"generated {n_pages} pages, {n_visuals} visuals under {ROOT}")


if __name__ == "__main__":
    main()
