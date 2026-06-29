"""Adapter: Solr response Incentivi.gov.it → BandoItem.

Endpoint: https://www.incentivi.gov.it/solr/coredrupal/select
Risposta Solr: {response: {docs: [...], numFound: N}}

Campi documento principali:
  zs_title, zs_url, zs_body, zs_nid,
  zs_field_open_date, zs_field_close_date,
  zm_field_regions_value[],
  zm_field_scopes_value[],          (programma/ambito)
  zm_field_activity_sector_value[],
  zs_field_ateco,
  zs_field_budget_allocation,
  zs_field_cost_min, zs_field_cost_max,
  zs_field_support_grant_type_min, zs_field_support_grant_type_max,
  zm_field_dimensions_value[],
  zm_field_subject_type_value[],
  zm_field_granted_costs_value[],
  zm_field_support_form_value[],
  zs_field_subject_grant,
  zs_field_primary_ruleset, zs_field_implementation_ruleset,
  zs_field_link
"""
from __future__ import annotations

from typing import Any

from ..base import BandoItem


_BASE_URL = "https://www.incentivi.gov.it"


def _to_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val)


def _to_float_or_none(val: Any) -> float | None:
    if val in (None, "", []):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def to_bando_item(doc: dict[str, Any], fonte_id: int) -> BandoItem | None:
    """Converte un documento Solr di Incentivi.gov.it in BandoItem.

    Skip silenzioso se mancano titolo o URL.
    """
    titolo = _to_str(doc.get("zs_title")).strip()
    url_path = _to_str(doc.get("zs_url")).strip()

    if not titolo or not url_path:
        return None

    link = url_path if url_path.startswith("http") else f"{_BASE_URL}{url_path}"

    descrizione = _to_str(doc.get("zs_body")).strip() or None
    if descrizione and len(descrizione) > 4000:
        descrizione = descrizione[:4000] + "..."

    # raw_data: tutti i campi finanziari ed extra per l'enricher LLM.
    raw_data: dict[str, Any] = {
        "source": "incentivi_gov_it",
        "nid": _to_str(doc.get("zs_nid")) or None,
        "open_date": _to_str(doc.get("zs_field_open_date")) or None,
        "close_date": _to_str(doc.get("zs_field_close_date")) or None,
        "regions": doc.get("zm_field_regions_value") or [],
        "scopes": doc.get("zm_field_scopes_value") or [],
        "activity_sectors": doc.get("zm_field_activity_sector_value") or [],
        "ateco": _to_str(doc.get("zs_field_ateco")) or None,
        "budget_allocation": _to_float_or_none(doc.get("zs_field_budget_allocation")),
        "cost_min": _to_float_or_none(doc.get("zs_field_cost_min")),
        "cost_max": _to_float_or_none(doc.get("zs_field_cost_max")),
        "support_grant_min": _to_float_or_none(doc.get("zs_field_support_grant_type_min")),
        "support_grant_max": _to_float_or_none(doc.get("zs_field_support_grant_type_max")),
        "dimensions": doc.get("zm_field_dimensions_value") or [],
        "subject_types": doc.get("zm_field_subject_type_value") or [],
        "granted_costs": doc.get("zm_field_granted_costs_value") or [],
        "support_forms": doc.get("zm_field_support_form_value") or [],
        "subject_grant": _to_str(doc.get("zs_field_subject_grant")) or None,
        "primary_ruleset": _to_str(doc.get("zs_field_primary_ruleset")) or None,
        "implementation_ruleset": _to_str(doc.get("zs_field_implementation_ruleset")) or None,
        "external_link": _to_str(doc.get("zs_field_link")) or None,
    }
    raw_data = {k: v for k, v in raw_data.items() if v not in (None, "", [], {})}

    return BandoItem(
        fonte_id=fonte_id,
        tipo_link="Opportunità",
        link_bando=link,
        titolo_raw=titolo,
        descrizione_raw=descrizione,
        raw_data=raw_data,
    )
