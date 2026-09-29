-- ============================================================================
-- Correzioni B e fusioni F dopo il giro delle 12 del 29/09/2026 — DB «bandi»
-- ============================================================================
-- Nate dal controllo dei 20 bandi pubblicati quel giro, confrontati uno per
-- uno con la fonte ufficiale (un verificatore più uno scettico per difetto),
-- e dal confronto sul DB. Blocchi indipendenti, da eseguire uno alla volta nel
-- SQL Editor, controllando il risultato atteso prima di passare al successivo.
-- Fuori dai giri delle 00/06/12/18. Stato e date passano da
-- bando_registra_evento; i doppioni da bando_fondi (nessuna riga cancellata,
-- il doppione resta completed con il suo slug e risponde 301 verso il master).
-- Ordine consigliato: B1 prima di F2, B2 prima di F3.
-- ============================================================================


-- ---------------------------------------------------------------------------
-- B1. Bando 1262082 (ricerca-partner-contrasto-abbandono-sociale-piemonte)
--     A DB scade il 14/10. La Regione l'ha prorogato con la DD 1516 del
--     28/09/2026: «di prorogare il termine per la presentazione delle
--     manifestazioni di interesse alle ore 23:59 di lunedì 19 ottobre».
--     La pagina del Piemonte è fra quelle che il monitor non vede (RIPRESA
--     §4.4); la stessa rettifica ha cambiato l'URL della pagina e ha fatto
--     nascere il doppione 1262345 (F2).
-- ---------------------------------------------------------------------------

-- prima: dominio verificante (atteso: true; se false, FERMARSI)
select public.bando_dominio_verificante(public.dominio_di(
  'https://bandi.regione.piemonte.it/system/files/DD-A22_1516_2026_rettifica.pdf'));

select public.bando_registra_evento(
  p_bando_id    => 1262082,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => '{"data_scadenza": "2026-10-19", "ora_scadenza": "23:59"}'::jsonb,
  p_url_prova   => 'https://bandi.regione.piemonte.it/system/files/DD-A22_1516_2026_rettifica.pdf',
  p_citazione   => 'di prorogare il termine per la presentazione delle manifestazioni di interesse alle ore 23:59 di lunedì 19 ottobre',
  p_data_evento => '2026-09-28',
  p_applica     => true,
  p_metodo      => 'correzione manuale del committente (controllo del 29/09): proroga non vista dal monitor'
);
-- atteso: {"id": <nuovo>, "nuovo": true, "applicato": true}

-- dopo (atteso: aperto | 2026-10-19 | 23:59:00 | true)
select stato_bando, data_scadenza, ora_scadenza, data_scadenza_verificata
  from bando where id = 1262082;


-- ---------------------------------------------------------------------------
-- B2. Bando 1262080 (polizia-locale-plus-2026-parte-corrente-lazio)
--     A DB è «in apertura prossimamente» senza date. La pagina ufficiale:
--     domande «dalle ore 09:00 del 28 settembre 2026 ed entro le ore 12:00
--     del 29 ottobre 2026». È il master del doppione 1262369 (F3), che oggi è
--     l'unica delle due schede con la scadenza giusta: va corretto prima di
--     fondere. in apertura → aperto per un'apertura del worker è nella lista
--     bianca.
-- ---------------------------------------------------------------------------

-- prima: dominio verificante (atteso: true; se false, FERMARSI)
select public.bando_dominio_verificante(public.dominio_di(
  'https://www.lazioeuropa.it/bandi/polizia-locale-plus-2026-parte-corrente/'));

select public.bando_registra_evento(
  p_bando_id    => 1262080,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => '{"data_apertura": "2026-09-28", "ora_apertura": "09:00", "data_scadenza": "2026-10-29", "ora_scadenza": "12:00", "stato_bando": "aperto"}'::jsonb,
  p_url_prova   => 'https://www.lazioeuropa.it/bandi/polizia-locale-plus-2026-parte-corrente/',
  p_citazione   => 'dalle ore 09:00 del 28 settembre 2026 ed entro le ore 12:00 del 29 ottobre 2026',
  p_data_evento => '2026-09-28',
  p_applica     => true,
  p_metodo      => 'correzione manuale del committente (controllo del 29/09): apertura e scadenza assenti a DB'
);
-- atteso: {"id": <nuovo>, "nuovo": true, "applicato": true}
-- se solleva 23514 (transizione non ammessa) non è stato scritto niente.

-- dopo (atteso: aperto | 2026-09-28 | 09:00:00 | 2026-10-29 | 12:00:00)
select stato_bando, data_apertura, ora_apertura, data_scadenza, ora_scadenza
  from bando where id = 1262080;


-- ---------------------------------------------------------------------------
-- B3. Bando 1262408 (gal-valle-aosta-bando-pif-progetti-integrati-filiera)
--     Importo sbagliato di un fattore 10, anche nel titolo: a DB 25.700.000 €
--     («25,7 milioni»), nel bando del GAL «La dotazione finanziaria prevista
--     per l'attuazione di questo bando (AS.3, AS.4, AS.5, AS.6) è
--     complessivamente pari a € 2.570.000,00». L'errore viene
--     dall'aggregatore ObiettivoEuropa (fonte 449), che scrive 25.700.000.
--     Non sono stato né date: UPDATE diretto, lo slug non contiene la cifra.
-- ---------------------------------------------------------------------------

-- prima (atteso: 25700000 | titolo e descrizione con «25,7 milioni» | true | true)
select importo_totale_eur, titolo, descrizione_breve,
       contenuto::text like '%25,7 milioni%' as testo_con_milioni,
       contenuto::text like '%25.700.000%'   as testo_con_cifra
  from bando where id = 1262408;

update bando
   set importo_totale_eur = 2570000,
       titolo            = replace(titolo, '25,7 milioni', '2,57 milioni'),
       descrizione_breve = replace(descrizione_breve, '25,7 milioni', '2,57 milioni'),
       contenuto         = replace(replace(contenuto::text, '25,7 milioni', '2,57 milioni'),
                                   '25.700.000', '2.570.000')::jsonb
 where id = 1262408 and importo_totale_eur = 25700000;
-- atteso: UPDATE 1

-- dopo (atteso: 2570000 | «2,57 milioni» nel titolo | false)
select importo_totale_eur, titolo,
       contenuto::text ~ '25,7 milioni|25\.700\.000' as resta_la_cifra_sbagliata
  from bando where id = 1262408;
-- Nota: se ObiettivoEuropa non corregge la cifra, una futura rielaborazione
-- della scheda può riportarla. Fonte ufficiale da agganciare:
-- https://www.gal.vda.it/bando/bando-pif-selezione-di-progetti-integrati-di-filiera/


-- ---------------------------------------------------------------------------
-- F1-F6. Sei doppioni pubblicati il 29/09, ciascuno confermato da due agenti
--     sulla fonte ufficiale e sul DB (stessa pagina, oppure stesso ente,
--     importo e scadenza). Il master è la scheda più vecchia, costruita sulla
--     fonte ufficiale; il doppione esce dal sito con un 301 verso il master.
--     Su BandoFit il doppione resta visibile fino alla sua fase (c) (RIPRESA
--     §4.4, voce L4): lo è anche adesso, quindi non peggiora niente.
--     bando_fondi può stampare una NOTICE se i criteri §14 preferirebbero
--     l'altro master: è solo un avviso.
-- ---------------------------------------------------------------------------

-- prima (atteso: 12 righe, tutte pubblicato = true e bando_master_id NULL)
select id, slug, pubblicato, bando_master_id, fonte_id, data_scadenza
  from bando
 where id in (1262344, 1262343, 1262345, 1262082, 1262369, 1262080,
              1262406, 1261867, 1262410, 1240069, 1262413, 1261831)
 order by id;

-- F1. Stessa pagina lazioeuropa.it da due fonti (235 e 237).
select public.bando_fondi(1262344, 1262343,
  'doppione verificato il 29/09: stessa pagina ufficiale (Business Opportunities, Lazio Innova) da due fonti');
-- F2. La rettifica del Piemonte ha cambiato l'URL della pagina (vedi B1).
select public.bando_fondi(1262345, 1262082,
  'doppione verificato il 29/09: stesso avviso, URL della pagina cambiato dalla rettifica DD 1516/2026');
-- F3. ObiettivoEuropa contro la pagina ufficiale lazioeuropa.it (dopo B2).
select public.bando_fondi(1262369, 1262080,
  'doppione verificato il 29/09: scheda ObiettivoEuropa dello stesso avviso Polizia Locale Plus 2026');
-- F4-F6. ObiettivoEuropa contro bandi.regione.piemonte.it.
select public.bando_fondi(1262406, 1261867,
  'doppione verificato il 29/09: scheda ObiettivoEuropa dello stesso avviso SOMS storiche');
select public.bando_fondi(1262410, 1240069,
  'doppione verificato il 29/09: scheda ObiettivoEuropa dello stesso avviso iniziative istituzionali');
select public.bando_fondi(1262413, 1261831,
  'doppione verificato il 29/09: scheda ObiettivoEuropa dello stesso avviso possesso responsabile');
-- atteso per ciascuna: l'id del master (1262343, 1262082, 1262080, 1261867, 1240069, 1261831)

-- dopo (atteso: 6 righe con pubblicato = false e bando_master_id = il master)
select id, pubblicato, bando_master_id from bando
 where id in (1262344, 1262345, 1262369, 1262406, 1262410, 1262413) order by id;
-- dopo (atteso: 6 righe, esito 301, bando_id = il master)
select s.slug, s.bando_id, s.esito
  from bando_slug_storico s
  join bando b on b.slug = s.slug
 where b.id in (1262344, 1262345, 1262369, 1262406, 1262410, 1262413)
 order by s.bando_id;
