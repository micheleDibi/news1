-- ==========================================
-- correzioni-giro-3.sql — DB «bandi»
-- Backfill di bando_link: candidature e
-- allegati dei pubblicati (giro 3, §10)
-- ==========================================
-- Scritto l'01/10/2026 da «db» (G3-D3).
-- Provato su Postgres 17 effimero, sulla
-- catena 01 → 13 eseguita dai file veri.
--
-- Perché
--   La 02 (23/09) ha copiato in bando_link
--   i link di candidatura e gli allegati
--   che le righe avevano allora. Per i
--   bandi pubblicati dopo, la SEO non
--   scrive righe di candidatura né di
--   allegato (lo farà dal giro 3: contratto
--   interno bandi-giro-3 §10). Quando la 07
--   toglierà dalla vista le colonne
--   vecchie, quei bandi perderebbero
--   pulsante e allegati.
--
-- Cosa fa
--   Solo INSERT in bando_link, solo per i
--   pubblicati, con origine 'raw' e
--   pubblicabile false (la pubblicabilità
--   la decide link_verifica):
--   A. tipo 'candidatura': link_candidatura
--      con link_candidatura_source =
--      'extracted' (non 'fallback_source',
--      che ricade sull'aggregatore);
--   B. tipo 'allegato': le voci di
--      bando.allegati ({label|nome, url,
--      tipo}); l'etichetta è label o nome
--      (con lo stesso URL ripetuto vale la
--      prima voce).
--   Una riga già presente con lo stesso
--   bando e lo stesso URL normalizzato, di
--   qualunque tipo, non si tocca (ON
--   CONFLICT ON CONSTRAINT
--   bando_link_url_uq DO NOTHING). Un URL
--   che è sia candidatura sia allegato
--   dello stesso bando entra una volta,
--   come candidatura. Nessuna riga di bando
--   cambia.
--
-- Ordine
--   Dopo la 02, che è applicata dal 23/09.
--   NON rieseguire la 02. Indipendente
--   dalla 14: va bene prima o dopo. Meglio
--   prima del deploy del giro 3, così il
--   primo link_verifica del giro trova
--   anche queste righe.
--   Rieseguibile: la seconda volta
--   inserisce 0 righe.
--
-- Come si applica
--   SQL Editor, un blocco alla volta:
--   0 (anteprima, sola lettura), 1
--   (scrittura, una sola istruzione), 2
--   (verifica, sola lettura).
--
-- Atteso (misurato l'01/10/2026 alle 16,
-- RIPRESA §8.5):
--   A. 3 righe (bandi 1260443, 1262056,
--      1262673);
--   B. 1 riga (bando 1260432).
--   Con i bandi pubblicati dopo l'01/10 i
--   numeri possono crescere di poco.
--
-- Il grosso del lavoro lo fa link_verifica
-- nel giro, non questo SQL: 70 candidature
-- e 272 allegati degli aperti hanno già la
-- loro riga, ma non pubblicabile (RIPRESA
-- §8.5). Dal giro 3 link_verifica le
-- controlla a ogni giro (quarta prova:
-- l'URL compare nella pagina di
-- riferimento) e le rende pubblicabili.
-- ==========================================


-- 0. Anteprima (sola lettura)
-- atteso: due righe, «allegato | 1» e
--   «candidatura | 3» (01/10/2026). Dopo
--   il blocco 1: zero righe.
with cand as (
  select distinct on (b.id, n.u)
         b.id as bando_id,
         btrim(b.link_candidatura) as url,
         n.u as url_norm
    from public.bando b
   cross join lateral (
     select public.bando_normalizza_url(
              btrim(b.link_candidatura)) as u
   ) n
   where b.pubblicato
     and b.link_candidatura_source
         = 'extracted'
     and b.link_candidatura is not null
     and btrim(b.link_candidatura) <> ''
     and n.u is not null
   order by b.id, n.u
),
alleg as (
  select distinct on (x.bando_id, x.url_norm)
         x.bando_id, x.url, x.url_norm,
         x.etichetta
    from (
      select b.id as bando_id,
             btrim(e.value ->> 'url') as url,
             public.bando_normalizza_url(
               btrim(e.value ->> 'url'))
               as url_norm,
             nullif(btrim(coalesce(
               e.value ->> 'label',
               e.value ->> 'nome', '')), '')
               as etichetta,
             e.pos
        from public.bando b
       cross join lateral
             jsonb_array_elements(
               case jsonb_typeof(b.allegati)
                 when 'array' then b.allegati
                 else '[]'::jsonb
               end)
             with ordinality as e(value, pos)
       where b.pubblicato
         and jsonb_typeof(e.value)
             = 'object'
    ) x
   where x.url is not null
     and x.url <> ''
     and x.url_norm is not null
     and not exists (
       select 1 from cand c
        where c.bando_id = x.bando_id
          and c.url_norm = x.url_norm)
   order by x.bando_id, x.url_norm, x.pos
),
nuove as (
  select 'candidatura' as tipo,
         c.bando_id, c.url_norm
    from cand c
  union all
  select 'allegato', a.bando_id,
         a.url_norm
    from alleg a
)
select n.tipo, count(*) as nuove,
       string_agg(distinct
         n.bando_id::text, ', ') as bandi
  from nuove n
 where not exists (
   select 1 from public.bando_link l
    where l.bando_id = n.bando_id
      and l.url_normalizzato = n.url_norm)
 group by n.tipo
 order by n.tipo;


-- 1. Scrittura: una sola istruzione, quindi
--    tutto o niente.
-- atteso: «allegato | 1» e
--   «candidatura | 3» (01/10/2026).
--   Rieseguita: «allegato | 0» e
--   «candidatura | 0».
with cand as (
  select distinct on (b.id, n.u)
         b.id as bando_id,
         btrim(b.link_candidatura) as url,
         n.u as url_norm
    from public.bando b
   cross join lateral (
     select public.bando_normalizza_url(
              btrim(b.link_candidatura)) as u
   ) n
   where b.pubblicato
     and b.link_candidatura_source
         = 'extracted'
     and b.link_candidatura is not null
     and btrim(b.link_candidatura) <> ''
     and n.u is not null
   order by b.id, n.u
),
alleg as (
  select distinct on (x.bando_id, x.url_norm)
         x.bando_id, x.url, x.url_norm,
         x.etichetta
    from (
      select b.id as bando_id,
             btrim(e.value ->> 'url') as url,
             public.bando_normalizza_url(
               btrim(e.value ->> 'url'))
               as url_norm,
             nullif(btrim(coalesce(
               e.value ->> 'label',
               e.value ->> 'nome', '')), '')
               as etichetta,
             e.pos
        from public.bando b
       cross join lateral
             jsonb_array_elements(
               case jsonb_typeof(b.allegati)
                 when 'array' then b.allegati
                 else '[]'::jsonb
               end)
             with ordinality as e(value, pos)
       where b.pubblicato
         and jsonb_typeof(e.value)
             = 'object'
    ) x
   where x.url is not null
     and x.url <> ''
     and x.url_norm is not null
     and not exists (
       select 1 from cand c
        where c.bando_id = x.bando_id
          and c.url_norm = x.url_norm)
   order by x.bando_id, x.url_norm, x.pos
),
ins_cand as (
  insert into public.bando_link
    (bando_id, url, tipo, origine,
     pubblicabile)
  select c.bando_id, c.url,
         'candidatura', 'raw', false
    from cand c
  on conflict on constraint
     bando_link_url_uq do nothing
  returning id
),
ins_alleg as (
  insert into public.bando_link
    (bando_id, url, tipo, origine,
     pubblicabile, etichetta)
  select a.bando_id, a.url, 'allegato',
         'raw', false, a.etichetta
    from alleg a
  on conflict on constraint
     bando_link_url_uq do nothing
  returning id
)
select 'allegato' as tipo,
       count(*) as inserite
  from ins_alleg
union all
select 'candidatura', count(*)
  from ins_cand
 order by 1;


-- 2. Verifica (sola lettura)
-- a) Rieseguire il blocco 0.
--    atteso: zero righe.
-- b) Le righe nate dal blocco 1 sono tutte
--    non pubblicabili, di origine raw, e
--    stanno su bandi pubblicati. Il
--    conteggio guarda SOLO i bandi che
--    l'anteprima ha elencato (colonna
--    «bandi» del blocco 0): dopo il deploy
--    del giro 3 anche la SEO e il monitor
--    scrivono righe di candidatura e di
--    allegato, che qui non devono entrare.
--    Al 01/10 i bandi sono i quattro qui
--    sotto; se l'anteprima ne ha elencati
--    altri, aggiungerli alla lista.
--    atteso: «allegato | 1 | 0 | 0» e
--    «candidatura | 3 | 0 | 0» la prima
--    volta (i numeri del blocco 1).
--    Più tardi link_verifica può rendere
--    pubblicabile qualcuna di queste righe:
--    è il suo lavoro, non un errore.
select l.tipo,
       count(*) as righe,
       count(*) filter (
         where l.pubblicabile)
         as pubblicabili,
       count(*) filter (
         where not b.pubblicato)
         as di_non_pubblicati
  from public.bando_link l
  join public.bando b on b.id = l.bando_id
 where l.origine = 'raw'
   and l.tipo in ('candidatura',
                  'allegato')
   and l.bando_id in (1260432, 1260443,
                      1262056, 1262673)
   and l.created_at
       >= date '2026-10-01'
 group by l.tipo
 order by l.tipo;
