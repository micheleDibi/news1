/**
 * Filtri della lista bandi (design «Bandi Redesign»): miglioramento progressivo
 * di ElencoBandi.astro. Senza questo script la pagina funziona lo stesso: il
 * pannello «Tutti i filtri» si apre col solo CSS e il form fa un GET normale.
 *
 * Cosa aggiunge:
 *  - le quattro tendine rapide (Regione, Tipologia, Beneficiario, Settore): le
 *    righe sono CLONI di quelle del pannello, senza `name`, cosi' nel form esiste
 *    una sola casella per valore e nessuna copia da tenere allineata a mano;
 *  - le etichette che il mock ricalcola a ogni scelta: testo e stato dei bottoni
 *    rapidi, «N selezionati», il contatore di «Tutti i filtri», i preset attivi,
 *    il link di reset (che conserva ordinamento e vista);
 *  - i preset di importo e scadenza;
 *  - «Mostra N bandi» chiude il pannello, «Cerca» porta ai risultati.
 *
 * Le etichette si calcolano con le stesse funzioni del server
 * (src/lib/bandi/elenco.ts): la pagina appena caricata e quella aggiornata dallo
 * script non possono dire cose diverse.
 */
import { contaAvanzati, etichettaRapida, PARAMETRI_PRESENTAZIONE } from '../lib/bandi/elenco';
import type { Valori } from '../lib/liste/parametri';
import { EVENTO_AGGIORNATA } from './lista';

export function attivaFiltriBandi(): void {
  const form = document.getElementById('filtri') as HTMLFormElement | null;
  if (!form) return;
  const modulo: HTMLFormElement = form;
  const velo = modulo.querySelector<HTMLElement>('[data-velo]');
  const pannello = document.getElementById('pannello-filtri') as HTMLInputElement | null;

  const valoriForm = (): Valori => {
    const valori: Valori = {};
    for (const [nome, valore] of new FormData(modulo)) {
      if (typeof valore === 'string' && valore !== '') (valori[nome] ??= []).push(valore);
    }
    return valori;
  };

  const gruppo = (chiave: string): HTMLElement | null => modulo.querySelector<HTMLElement>(`[data-gruppo="${chiave}"]`);
  const caselleGruppo = (chiave: string): HTMLInputElement[] =>
    [...(gruppo(chiave)?.querySelectorAll<HTMLInputElement>('input[type="checkbox"]') ?? [])];

  // -------------------------------------------------------------------------
  // Etichette calcolate
  // -------------------------------------------------------------------------

  function aggiornaEtichette(): void {
    const valori = valoriForm();

    for (const radice of modulo.querySelectorAll<HTMLElement>('[data-rapido]')) {
      const chiave = radice.dataset.rapido ?? '';
      const scelte = caselleGruppo(chiave)
        .filter((c) => c.checked)
        .map((c) => c.closest('label')?.querySelector('.riga-testo')?.textContent?.trim() ?? '');
      const testo = radice.querySelector<HTMLElement>('[data-rapido-testo]');
      if (testo) testo.textContent = etichettaRapida(gruppo(chiave)?.dataset.etichetta ?? chiave, scelte);
      radice.querySelector<HTMLElement>('[data-rapido-apri]')?.toggleAttribute('data-attivo', scelte.length > 0);
    }

    for (const etichetta of modulo.querySelectorAll<HTMLElement>('[data-selezionati]')) {
      const n = caselleGruppo(etichetta.dataset.selezionati ?? '').filter((c) => c.checked).length;
      etichetta.textContent = n ? `${n} selezionati` : '';
    }

    const contatore = modulo.querySelector<HTMLElement>('[data-contatore-filtri]');
    if (contatore) {
      const n = contaAvanzati(valori);
      contatore.textContent = String(n);
      contatore.classList.toggle('hidden', n === 0);
      contatore.classList.toggle('inline-flex', n > 0);
    }

    for (const bottone of modulo.querySelectorAll<HTMLButtonElement>('[data-preset]')) {
      const [nomeDa, nomeA] = bottone.dataset.preset === 'importo' ? ['imin', 'imax'] : ['scad_da', 'scad_a'];
      const attivo = (valori[nomeDa]?.[0] ?? '') === (bottone.dataset.da ?? '')
        && (valori[nomeA]?.[0] ?? '') === (bottone.dataset.a ?? '');
      bottone.setAttribute('aria-pressed', attivo ? 'true' : 'false');
    }

    // Il reset toglie i filtri e tiene ordinamento e vista, come nel mock.
    const tenuti = new URLSearchParams();
    for (const nome of PARAMETRI_PRESENTAZIONE) for (const v of valori[nome] ?? []) tenuti.append(nome, v);
    const coda = tenuti.toString();
    for (const reset of modulo.querySelectorAll<HTMLAnchorElement>('[data-reset]')) {
      reset.href = `${modulo.getAttribute('action') ?? '/bandi'}${coda ? `?${coda}` : ''}`;
    }
  }

  // -------------------------------------------------------------------------
  // Tendine rapide
  // -------------------------------------------------------------------------

  let aperta: HTMLElement | null = null;

  /** Le righe della tendina: cloni delle righe del pannello, senza `name`. */
  function riempiTendina(radice: HTMLElement): void {
    const elenco = radice.querySelector<HTMLElement>('[data-tendina-elenco]');
    const origine = gruppo(radice.dataset.rapido ?? '');
    if (!elenco || !origine) return;
    elenco.replaceChildren();
    for (const riga of origine.querySelectorAll<HTMLLabelElement>('label.riga-pannello')) {
      const casellaOrigine = riga.querySelector<HTMLInputElement>('input');
      if (!casellaOrigine) continue;
      const copia = riga.cloneNode(true) as HTMLLabelElement;
      copia.className = 'riga-tendina';
      copia.hidden = false;
      const casella = copia.querySelector<HTMLInputElement>('input');
      if (!casella) continue;
      casella.removeAttribute('name');
      casella.checked = casellaOrigine.checked;
      casella.addEventListener('change', () => {
        casellaOrigine.checked = casella.checked;
        casellaOrigine.dispatchEvent(new Event('change', { bubbles: true }));
      });
      elenco.appendChild(copia);
    }
    filtraTendina(radice);
  }

  function filtraTendina(radice: HTMLElement): void {
    const cerca = radice.querySelector<HTMLInputElement>('[data-tendina-cerca]');
    // Senza trim, come `dropQ.toLowerCase()` del mock.
    const testo = (cerca?.value ?? '').toLowerCase();
    for (const riga of radice.querySelectorAll<HTMLElement>('.riga-tendina')) {
      const etichetta = riga.querySelector('.riga-testo')?.textContent?.toLowerCase() ?? '';
      riga.hidden = testo !== '' && !etichetta.includes(testo);
    }
  }

  /** Riallinea le caselle clonate alle originali (dopo Pulisci, reset, Indietro). */
  function riallineaTendina(): void {
    if (!aperta) return;
    const originali = caselleGruppo(aperta.dataset.rapido ?? '');
    aperta.querySelectorAll<HTMLInputElement>('.riga-tendina input').forEach((c, i) => {
      if (originali[i]) c.checked = originali[i].checked;
    });
  }

  function chiudiTendina(): void {
    if (!aperta) return;
    const tendina = aperta.querySelector<HTMLElement>('[data-tendina]');
    if (tendina) tendina.hidden = true;
    aperta.querySelector('[data-rapido-apri]')?.setAttribute('aria-expanded', 'false');
    aperta = null;
    if (velo) velo.hidden = true;
  }

  /** `daTastiera`: aperta con Invio o Spazio. Solo allora il focus va nel campo di ricerca (il mock non lo sposta). */
  function apriTendina(radice: HTMLElement, daTastiera: boolean): void {
    chiudiTendina();
    // Tendina e pannello non stanno aperti insieme (come nel mock).
    if (pannello?.checked) pannello.checked = false;
    const tendina = radice.querySelector<HTMLElement>('[data-tendina]');
    if (!tendina) return;
    const cerca = radice.querySelector<HTMLInputElement>('[data-tendina-cerca]');
    if (cerca) cerca.value = '';
    riempiTendina(radice);
    tendina.hidden = false;
    radice.querySelector('[data-rapido-apri]')?.setAttribute('aria-expanded', 'true');
    if (velo) velo.hidden = false;
    aperta = radice;
    if (daTastiera) cerca?.focus();
  }

  for (const radice of modulo.querySelectorAll<HTMLElement>('[data-rapido]')) {
    radice.querySelector('[data-rapido-apri]')?.addEventListener('click', (e) => {
      if (aperta === radice) chiudiTendina();
      // Un clic generato da tastiera ha `detail` 0.
      else apriTendina(radice, (e as MouseEvent).detail === 0);
    });
    radice.querySelector('[data-tendina-cerca]')?.addEventListener('input', () => filtraTendina(radice));
    radice.querySelector('[data-tendina-fatto]')?.addEventListener('click', () => {
      chiudiTendina();
      radice.querySelector<HTMLElement>('[data-rapido-apri]')?.focus();
    });
    radice.querySelector('[data-tendina-pulisci]')?.addEventListener('click', () => {
      const scelte = caselleGruppo(radice.dataset.rapido ?? '').filter((c) => c.checked);
      for (const c of scelte) c.checked = false;
      scelte.at(-1)?.dispatchEvent(new Event('change', { bubbles: true }));
      riallineaTendina();
    });
  }

  // Il velo trasparente prende il clic fuori dalla tendina, come l'overlay del
  // mock: il clic non arriva alla card che sta sotto.
  velo?.addEventListener('click', chiudiTendina);
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !aperta) return;
    const bottone = aperta.querySelector<HTMLElement>('[data-rapido-apri]');
    chiudiTendina();
    bottone?.focus();
  });
  pannello?.addEventListener('change', () => {
    if (pannello.checked) chiudiTendina();
  });

  // -------------------------------------------------------------------------
  // Preset, «Mostra», «Cerca»
  // -------------------------------------------------------------------------

  for (const bottone of modulo.querySelectorAll<HTMLButtonElement>('[data-preset]')) {
    bottone.addEventListener('click', () => {
      const [nomeDa, nomeA] = bottone.dataset.preset === 'importo' ? ['imin', 'imax'] : ['scad_da', 'scad_a'];
      const da = modulo.elements.namedItem(nomeDa) as HTMLInputElement | null;
      const a = modulo.elements.namedItem(nomeA) as HTMLInputElement | null;
      if (!da || !a) return;
      da.value = bottone.dataset.da ?? '';
      a.value = bottone.dataset.a ?? '';
      a.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  // «Cerca» porta ai risultati come `goResults` del mock: la barra dei filtri
  // arriva a 76px dall'alto (nel mock: scroll a 620px, barra a 696px). Il conto
  // parte dalla fine della testata, cosi' vale anche con testate piu' alte.
  // «Mostra N bandi» chiude soltanto il pannello, la pagina resta dov'e'.
  const testata = modulo.querySelector<HTMLElement>('[data-testata-lista]');
  // Invio in un campo non invia il form: nel mock i campi aggiornano la lista
  // mentre si scrive e Invio non fa nulla. Senza questo, l'invio implicito
  // userebbe «Cerca» (il primo bottone del form) e farebbe scorrere la pagina.
  modulo.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target instanceof HTMLInputElement) e.preventDefault();
  });
  modulo.addEventListener('submit', (e) => {
    const invio = (e as SubmitEvent).submitter;
    if (invio?.hasAttribute('data-mostra')) {
      if (pannello) pannello.checked = false;
    } else if (invio?.hasAttribute('data-cerca-invio') && testata) {
      const fineTestata = testata.getBoundingClientRect().bottom + window.scrollY;
      window.scrollTo({ top: Math.max(0, fineTestata - 76), behavior: 'smooth' });
    }
  });

  // L'altezza della barra sticky (una o piu' righe secondo la larghezza) come
  // variabile CSS: e' lo scroll-margin della lista, cosi' cambiando pagina la
  // prima card non finisce sotto la barra.
  const barra = modulo.querySelector<HTMLElement>('[data-barra]');
  if (barra) {
    const misura = (): void => modulo.style.setProperty('--altezza-barra', `${barra.offsetHeight}px`);
    misura();
    new ResizeObserver(misura).observe(barra);
  }

  modulo.addEventListener('change', () => {
    aggiornaEtichette();
    riallineaTendina();
  });
  modulo.addEventListener('input', aggiornaEtichette);
  document.addEventListener(EVENTO_AGGIORNATA, () => {
    aggiornaEtichette();
    riallineaTendina();
  });
  aggiornaEtichette();
}
