from __future__ import annotations

import json
from types import SimpleNamespace
import uuid

import pytest

from app.db.connection import get_db_connection, get_raw_connection
from app.repos.base import BandoRepo, ReferenceDataRepo
from app.services.classification_service import (
    ControlledClassificationService,
    ReferenceCatalog,
    ReferenceOption,
    _normalize_text,
)


def test_controlled_matching_exact():
    service = ControlledClassificationService(catalog=_build_test_catalog())

    payload = {
        "titolo": "Bando regionale Abruzzo Fondo perduto AGRIP",
        "descrizione": "Misura per agricoltura e sviluppo rurale rivolta ad Agenzie per il lavoro. Codice ateco 01.",
        "link_bando": "https://example.org/bando",
        "raw_data_obj": {},
        "data_extra": {},
    }

    classified = service.classify_candidate(
        payload,
        fonte=SimpleNamespace(titolo="Programma Regionale"),
    )

    assert classified["is_bando_confermato"] is True
    assert classified["tipologia_bando_id"] == 3
    assert classified["modalita_erogazione_id"] == 1
    assert classified["programma_id"] == 1
    assert classified["regione_ids"] == [1]
    assert classified["settore_ids"] == [5]
    assert classified["beneficiario_ids"] == [1]
    assert classified["codice_ateco_ids"] == [1]


def test_controlled_matching_fuzzy():
    service = ControlledClassificationService(catalog=_build_test_catalog())

    payload = {
        "titolo": "Contributo per emilia romagn",
        "descrizione": "Intervento per agricoltura e svilupo rurale con fondo perduto",
        "link_bando": "https://example.org/bando-fuzzy",
        "raw_data_obj": {},
        "data_extra": {},
    }

    classified = service.classify_candidate(payload)

    assert classified["is_bando_confermato"] is True
    assert classified["modalita_erogazione_id"] == 1
    assert 5 in classified["regione_ids"]
    assert 5 in classified["settore_ids"]


def test_controlled_matching_rejects_obvious_non_bando_link():
    service = ControlledClassificationService(catalog=_build_test_catalog())

    payload = {
        "titolo": "Privacy policy",
        "descrizione": "Informativa sui cookie e contatti",
        "link_bando": "https://example.org/privacy",
        "raw_data_obj": {
            "link_diagnostics": {
                "accepted": False,
                "score": 0,
                "reason_reject": "DENY_PATH",
            }
        },
        "data_extra": {},
    }

    classified = service.classify_candidate(payload)

    assert classified["is_bando_confermato"] is False


def test_ai_output_validator_scarta_valori_non_presenti():
    service = ControlledClassificationService(catalog=_build_test_catalog())
    validator = service.build_ai_validator()

    validated = validator.validate(
        {
            "programma_id": 999,
            "modalita_erogazione_id": "Fondo perduto",
            "regione_ids": ["Abruzzo", "Atlantide", 1],
            "beneficiario_ids": ["Agenzie per il lavoro", "Soggetto inesistente"],
            "campo_non_previsto": 123,
        }
    )

    assert validated == {
        "modalita_erogazione_id": 1,
        "regione_ids": [1],
        "beneficiario_ids": [1],
    }


@pytest.mark.integration
def test_classification_upsert_persists_fk_and_bridge_rows():
    fonte_id = _get_any_fonte_id()
    repo = BandoRepo()
    service = ControlledClassificationService()
    unique_hash = f"m6-hash-{uuid.uuid4()}"
    unique_link = f"https://example.org/m6/{uuid.uuid4()}"

    payload = {
        "fonte_id": fonte_id,
        "titolo": "Bando regionale Abruzzo Fondo perduto AGRIP",
        "descrizione": "Intervento per agricoltura e sviluppo rurale dedicato ad Agenzie per il lavoro. Codice ATECO 01.",
        "codice_bando": "M6-TEST",
        "stato_bando": "aperto",
        "link_bando": unique_link,
        "hash_bando": unique_hash,
        "raw_data_obj": {"candidate_title": "AGRIP Abruzzo Fondo perduto"},
        "raw_data": json.dumps({"candidate_title": "AGRIP Abruzzo Fondo perduto"}),
        "data_extra": {},
    }

    try:
        classified_payload = service.classify_candidates([payload])[0]
        stats = repo.upsert_candidates([classified_payload])
        assert stats["inserted"] == 1

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, tipologia_bando_id, modalita_erogazione_id, programma_id, is_bando_confermato
                    FROM public.bando
                    WHERE hash_bando = %s
                    """,
                    (unique_hash,),
                )
                bando_row = cur.fetchone()

                assert bando_row is not None
                assert bando_row["tipologia_bando_id"] is not None
                assert bando_row["modalita_erogazione_id"] is not None
                assert bando_row["programma_id"] is not None
                assert bando_row["is_bando_confermato"] is True

                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM public.bando_regioni br
                    JOIN public.regioni r ON r.id = br.regione_id
                    WHERE br.bando_id = %s
                    """,
                    (bando_row["id"],),
                )
                assert cur.fetchone()["cnt"] >= 1

                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM public.bando_settori bs
                    JOIN public.settori s ON s.id = bs.settore_id
                    WHERE bs.bando_id = %s
                    """,
                    (bando_row["id"],),
                )
                assert cur.fetchone()["cnt"] >= 1

                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM public.bando_codici_ateco ba
                    JOIN public.codici_ateco ca ON ca.id = ba.codice_ateco_id
                    WHERE ba.bando_id = %s
                    """,
                    (bando_row["id"],),
                )
                assert cur.fetchone()["cnt"] >= 1
    finally:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM public.bando_beneficiari WHERE bando_id IN (SELECT id FROM public.bando WHERE hash_bando = %s)",
                    (unique_hash,),
                )
                cur.execute(
                    "DELETE FROM public.bando_codici_ateco WHERE bando_id IN (SELECT id FROM public.bando WHERE hash_bando = %s)",
                    (unique_hash,),
                )
                cur.execute(
                    "DELETE FROM public.bando_regioni WHERE bando_id IN (SELECT id FROM public.bando WHERE hash_bando = %s)",
                    (unique_hash,),
                )
                cur.execute(
                    "DELETE FROM public.bando_settori WHERE bando_id IN (SELECT id FROM public.bando WHERE hash_bando = %s)",
                    (unique_hash,),
                )
                cur.execute("DELETE FROM public.bando_storico WHERE bando_id IN (SELECT id FROM public.bando WHERE hash_bando = %s)", (unique_hash,))
                cur.execute("DELETE FROM public.bando WHERE hash_bando = %s", (unique_hash,))


@pytest.mark.integration
def test_reinvocation_uses_new_lookup_values_added_manually_to_db():
    temp_name = f"Settore Test M6 {uuid.uuid4()}"
    conn = get_raw_connection()
    inserted_id = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.settori (nome) VALUES (%s) RETURNING id",
                (temp_name,),
            )
            inserted_id = int(cur.fetchone()["id"])
        conn.commit()

        service = ControlledClassificationService()
        classified = service.classify_candidate(
            {
                "titolo": f"Avviso {temp_name}",
                "descrizione": f"Misura dedicata al {temp_name}",
                "link_bando": "https://example.org/new-lookup",
                "raw_data_obj": {},
                "data_extra": {},
            }
        )

        assert inserted_id is not None
        assert inserted_id in classified["settore_ids"]
        assert ReferenceDataRepo.bridge_table_exists("bando_beneficiari") is True
    finally:
        with conn.cursor() as cur:
            if inserted_id is not None:
                cur.execute("DELETE FROM public.bando_settori WHERE settore_id = %s", (inserted_id,))
                cur.execute("DELETE FROM public.settori WHERE id = %s", (inserted_id,))
        conn.commit()
        conn.close()


def _build_test_catalog() -> ReferenceCatalog:
    return ReferenceCatalog(
        tipologie_bando=(
            _option(1, "Bandi Europei"),
            _option(2, "Bandi nazionali / PNRR"),
            _option(3, "Bandi regionali / locali"),
        ),
        modalita_erogazione=(
            _option(1, "Fondo perduto"),
            _option(2, "Tasso Agevolato"),
        ),
        programmi=(
            _option(1, "AGRIP - Promozione dei prodotti agricoli", aliases=("AGRIP", "Promozione dei prodotti agricoli")),
        ),
        regioni=(
            _option(1, "Abruzzo", aliases=("abruzzo",)),
            _option(5, "Emilia-Romagna", aliases=("emilia romagna",)),
        ),
        settori=(
            _option(5, "Agricoltura e sviluppo rurale"),
        ),
        beneficiari=(
            _option(1, "Agenzie per il lavoro"),
        ),
        codici_ateco=(
            _option(
                1,
                "01 Coltivazioni agricole e produzione di prodotti animali, caccia e servizi connessi",
                aliases=("01", "coltivazioni agricole e produzione di prodotti animali caccia e servizi connessi"),
            ),
        ),
        categoria_programma=(
            _option(1, "Programma Regionale"),
        ),
        tipologia_programma=(
            _option(1, "PR FESR"),
        ),
    )


def _option(identifier: int, label: str, aliases: tuple[str, ...] = ()) -> ReferenceOption:
    return ReferenceOption(
        id=identifier,
        label=label,
        normalized=_normalize_text(label),
        tokens=tuple(token for token in _normalize_text(label).split() if len(token) > 2),
        aliases=tuple(_normalize_text(alias) for alias in aliases if alias),
    )


def _get_any_fonte_id() -> int:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM public.fonte ORDER BY id LIMIT 1")
            row = cur.fetchone()
    assert row is not None, "Nessuna fonte disponibile per il test integrazione M6"
    return int(row["id"])