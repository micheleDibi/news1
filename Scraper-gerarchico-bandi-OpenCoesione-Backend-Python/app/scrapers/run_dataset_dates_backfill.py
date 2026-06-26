"""
Runner CLI per backfill controllato delle date sui bandi esistenti.

Uso:
    python -m app.scrapers.run_dataset_dates_backfill
    python -m app.scrapers.run_dataset_dates_backfill --apply
    python -m app.scrapers.run_dataset_dates_backfill --apply --limit 200
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from app.config.settings import settings
from app.db.connection import get_db_connection
from app.parsers.bando_parser import parse_bando_fields


def _raw_to_obj(raw_data: Any) -> dict[str, Any]:
    if raw_data is None:
        return {}
    if isinstance(raw_data, dict):
        return raw_data
    if isinstance(raw_data, str):
        try:
            parsed = json.loads(raw_data)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _resolve_importo_threshold(cli_threshold: str | None) -> Decimal:
    if cli_threshold:
        try:
            return max(Decimal(cli_threshold), Decimal("0"))
        except InvalidOperation:
            pass
    return max(Decimal(str(settings.importo_plausibile_threshold)), Decimal("0"))


def _run_backfill(
    apply_changes: bool,
    limit: int | None,
    *,
    upgrade_low_importo: bool,
    importo_threshold: Decimal,
) -> dict[str, Any]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            sql = (
                "SELECT id, titolo, link_bando, raw_data, data_pubblicazione, data_apertura, data_scadenza, importo, importo_numerico "
                "FROM public.bando "
                "WHERE data_pubblicazione IS NULL OR data_apertura IS NULL OR data_scadenza IS NULL OR importo_numerico IS NULL "
                "ORDER BY id ASC"
            )
            if upgrade_low_importo:
                sql = (
                    "SELECT id, titolo, link_bando, raw_data, data_pubblicazione, data_apertura, data_scadenza, importo, importo_numerico "
                    "FROM public.bando "
                    "WHERE data_pubblicazione IS NULL OR data_apertura IS NULL OR data_scadenza IS NULL "
                    "OR importo_numerico IS NULL OR importo_numerico <= %s "
                    "ORDER BY id ASC"
                )
            if limit is not None:
                sql += " LIMIT %s"
                if upgrade_low_importo:
                    cur.execute(sql, (importo_threshold, limit))
                else:
                    cur.execute(sql, (limit,))
            else:
                if upgrade_low_importo:
                    cur.execute(sql, (importo_threshold,))
                else:
                    cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]

            scanned = len(rows)
            candidates = 0
            updates = 0
            filled_pub = 0
            filled_ape = 0
            filled_sca = 0
            filled_importo = 0
            filled_importo_num = 0
            upgraded_importo_num = 0
            touched_ids: list[int] = []

            for row in rows:
                raw_obj = _raw_to_obj(row.get("raw_data"))
                parsed = parse_bando_fields(
                    title=str(row.get("titolo") or ""),
                    link_bando=str(row.get("link_bando") or ""),
                    raw_data_obj=raw_obj,
                )

                new_pub = row.get("data_pubblicazione") or parsed.data_pubblicazione
                new_ape = row.get("data_apertura") or parsed.data_apertura
                new_sca = row.get("data_scadenza") or parsed.data_scadenza
                new_importo = row.get("importo") or parsed.importo
                existing_importo_num = row.get("importo_numerico")
                parsed_importo_num = parsed.importo_numerico

                should_upgrade_low_importo = bool(
                    upgrade_low_importo
                    and existing_importo_num is not None
                    and parsed_importo_num is not None
                    and Decimal(str(existing_importo_num)) <= importo_threshold
                    and Decimal(str(parsed_importo_num)) > importo_threshold
                    and Decimal(str(parsed_importo_num)) > Decimal(str(existing_importo_num))
                )

                if should_upgrade_low_importo:
                    new_importo_num = parsed_importo_num
                else:
                    new_importo_num = existing_importo_num or parsed_importo_num

                will_fill_pub = row.get("data_pubblicazione") is None and new_pub is not None
                will_fill_ape = row.get("data_apertura") is None and new_ape is not None
                will_fill_sca = row.get("data_scadenza") is None and new_sca is not None
                will_fill_importo = row.get("importo") is None and new_importo is not None
                will_fill_importo_num = row.get("importo_numerico") is None and new_importo_num is not None
                will_upgrade_importo_num = should_upgrade_low_importo

                if not (
                    will_fill_pub
                    or will_fill_ape
                    or will_fill_sca
                    or will_fill_importo
                    or will_fill_importo_num
                    or will_upgrade_importo_num
                ):
                    continue

                candidates += 1
                if will_fill_pub:
                    filled_pub += 1
                if will_fill_ape:
                    filled_ape += 1
                if will_fill_sca:
                    filled_sca += 1
                if will_fill_importo:
                    filled_importo += 1
                if will_fill_importo_num:
                    filled_importo_num += 1
                if will_upgrade_importo_num:
                    upgraded_importo_num += 1

                if apply_changes:
                    if will_upgrade_importo_num:
                        cur.execute(
                            """
                            UPDATE public.bando
                            SET
                                data_pubblicazione = COALESCE(data_pubblicazione, %s),
                                data_apertura = COALESCE(data_apertura, %s),
                                data_scadenza = COALESCE(data_scadenza, %s),
                                importo = COALESCE(importo, %s),
                                importo_numerico = %s
                            WHERE id = %s
                            """,
                            (new_pub, new_ape, new_sca, new_importo, new_importo_num, row["id"]),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE public.bando
                            SET
                                data_pubblicazione = COALESCE(data_pubblicazione, %s),
                                data_apertura = COALESCE(data_apertura, %s),
                                data_scadenza = COALESCE(data_scadenza, %s),
                                importo = COALESCE(importo, %s),
                                importo_numerico = COALESCE(importo_numerico, %s)
                            WHERE id = %s
                            """,
                            (new_pub, new_ape, new_sca, new_importo, new_importo_num, row["id"]),
                        )
                    if cur.rowcount > 0:
                        updates += 1
                        touched_ids.append(int(row["id"]))

            if apply_changes:
                conn.commit()

    return {
        "apply": apply_changes,
        "scanned": scanned,
        "candidates": candidates,
        "updated": updates,
        "filled_data_pubblicazione": filled_pub,
        "filled_data_apertura": filled_ape,
        "filled_data_scadenza": filled_sca,
        "filled_importo": filled_importo,
        "filled_importo_numerico": filled_importo_num,
        "upgraded_importo_numerico": upgraded_importo_num,
        "importo_threshold": str(importo_threshold),
        "upgrade_low_importo": upgrade_low_importo,
        "sample_updated_ids": touched_ids[:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill date mancanti da raw_data/titolo/link")
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Applica gli update sul DB (default: dry-run)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Numero massimo di record da analizzare",
    )
    parser.add_argument(
        "--upgrade-low-importo",
        action="store_true",
        default=False,
        help="Aggiorna anche importo_numerico <= soglia se il parser trova un valore migliore sopra soglia",
    )
    parser.add_argument(
        "--importo-threshold",
        type=str,
        default=None,
        help="Soglia importo plausibile (default da settings: IMPORTO_PLAUSIBILE_THRESHOLD)",
    )
    args = parser.parse_args()

    threshold = _resolve_importo_threshold(args.importo_threshold)

    report = _run_backfill(
        apply_changes=args.apply,
        limit=args.limit,
        upgrade_low_importo=args.upgrade_low_importo,
        importo_threshold=threshold,
    )

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"DATASET DATE BACKFILL ({mode})")
    print(f"Record analizzati: {report['scanned']}")
    print(f"Record candidati update: {report['candidates']}")
    print(f"Record aggiornati: {report['updated']}")
    print(
        "Campi compilabili (date): "
        f"pubblicazione={report['filled_data_pubblicazione']}, "
        f"apertura={report['filled_data_apertura']}, "
        f"scadenza={report['filled_data_scadenza']}"
    )
    print(
        "Campi compilabili (importi): "
        f"importo={report['filled_importo']}, "
        f"importo_numerico={report['filled_importo_numerico']}, "
        f"importo_numerico_upgraded={report['upgraded_importo_numerico']}"
    )
    print(
        "Configurazione importo: "
        f"upgrade_low_importo={report['upgrade_low_importo']}, "
        f"threshold={report['importo_threshold']}"
    )
    if report["sample_updated_ids"]:
        print(f"Sample ID aggiornati: {report['sample_updated_ids']}")


if __name__ == "__main__":
    main()
