/**
 * Comportamento delle tendine a scelta multipla di /bandi.
 *
 * Le opzioni NON sono piu' iniettate da JavaScript: sono checkbox reali renderizzate
 * dal server dentro il form, quindi i filtri funzionano anche senza JavaScript e
 * dall'HTML sparisce il payload che serializzava tutti i codici ATECO, i settori e i
 * programmi (piu' URL e chiave anon di Supabase).
 *
 * Qui resta solo l'interazione: apri/chiudi il popover, filtra le voci con la ricerca
 * interna, aggiorna l'etichetta e il contatore, pulisci.
 */

const CHIAVE_COLLASSO = 'bandi:filters-collapsed';

export function attivaFiltriBandi(): void {
  for (const root of document.querySelectorAll<HTMLElement>('.multiselect')) attivaMultiselect(root);
  attivaPannello();
  aggiornaBadgeAttivi();
  document.getElementById('filtri')?.addEventListener('change', aggiornaBadgeAttivi);
}

function attivaMultiselect(root: HTMLElement): void {
  const trigger = root.querySelector<HTMLButtonElement>('.ms-trigger');
  const popover = root.querySelector<HTMLElement>('.ms-popover');
  const ricerca = root.querySelector<HTMLInputElement>('.ms-search');
  const pulisci = root.querySelector<HTMLButtonElement>('.ms-clear');
  if (!trigger || !popover) return;

  const caselle = () => [...root.querySelectorAll<HTMLInputElement>('.ms-list input[type="checkbox"]')];

  const aggiorna = () => {
    const scelte = caselle().filter((c) => c.checked);
    const display = root.querySelector<HTMLElement>('.ms-display');
    const contatore = root.querySelector<HTMLElement>('.ms-count');
    const stato = root.querySelector<HTMLElement>('.ms-status');
    if (display) {
      const vuoto = display.dataset.empty ?? '';
      display.textContent = scelte.length === 0
        ? vuoto
        : scelte.length === 1
          ? (scelte[0].closest('label')?.textContent?.trim() || vuoto)
          : `${scelte.length} selezionati`;
      display.classList.toggle('text-gray-500', scelte.length === 0);
      display.classList.toggle('text-gray-900', scelte.length > 0);
    }
    if (contatore) {
      contatore.textContent = String(scelte.length);
      contatore.classList.toggle('hidden', scelte.length === 0);
    }
    if (stato) stato.textContent = `${scelte.length} selezionati`;
  };

  trigger.addEventListener('click', (e) => {
    e.preventDefault();
    const aperto = !popover.classList.contains('hidden');
    for (const altro of document.querySelectorAll('.ms-popover')) altro.classList.add('hidden');
    popover.classList.toggle('hidden', aperto);
    if (!aperto) ricerca?.focus();
  });

  document.addEventListener('click', (e) => {
    if (!root.contains(e.target as Node)) popover.classList.add('hidden');
  });

  ricerca?.addEventListener('input', () => {
    const testo = ricerca.value.trim().toLowerCase();
    for (const etichetta of root.querySelectorAll<HTMLElement>('.ms-list label')) {
      etichetta.hidden = testo !== '' && !(etichetta.textContent ?? '').toLowerCase().includes(testo);
    }
  });

  pulisci?.addEventListener('click', (e) => {
    e.preventDefault();
    for (const c of caselle()) c.checked = false;
    aggiorna();
    root.closest('form')?.dispatchEvent(new Event('change', { bubbles: true }));
  });

  root.addEventListener('change', aggiorna);
  aggiorna();
}

/** Pannello filtri collassabile, con lo stato ricordato in localStorage. */
function attivaPannello(): void {
  const toggle = document.getElementById('filters-toggle');
  const corpo = document.getElementById('filters-body');
  const chevron = document.getElementById('filters-chevron');
  if (!toggle || !corpo) return;

  // Se l'URL porta gia' dei filtri il pannello si apre comunque, altrimenti l'utente
  // atterrerebbe su una lista filtrata senza vedere da cosa.
  const conFiltri = [...new URLSearchParams(window.location.search).keys()].some((k) => k !== 'page');
  let chiuso = conFiltri ? false : localStorage.getItem(CHIAVE_COLLASSO) === '1';
  if (!conFiltri && localStorage.getItem(CHIAVE_COLLASSO) === null) {
    chiuso = window.matchMedia('(max-width: 640px)').matches;
  }

  const applica = () => {
    corpo.classList.toggle('hidden', chiuso);
    chevron?.classList.toggle('rotate-180', !chiuso);
  };
  applica();

  toggle.addEventListener('click', (e) => {
    if ((e.target as HTMLElement).closest('[data-no-toggle="true"]')) return;
    chiuso = !chiuso;
    try {
      localStorage.setItem(CHIAVE_COLLASSO, chiuso ? '1' : '0');
    } catch {
      /* modalita' privata: si ignora */
    }
    applica();
  });
}

function aggiornaBadgeAttivi(): void {
  const form = document.getElementById('filtri') as HTMLFormElement | null;
  if (!form) return;
  let attivi = 0;
  for (const [, valore] of new FormData(form) as unknown as Iterable<[string, string]>) {
    if (valore !== '') attivi++;
  }
  const badge = document.getElementById('active-filters-badge');
  const conteggio = document.getElementById('active-count');
  const plurale = document.getElementById('active-pluralize');
  if (conteggio) conteggio.textContent = String(attivi);
  if (plurale) plurale.textContent = attivi === 1 ? 'o' : 'i';
  badge?.classList.toggle('hidden', attivi === 0);
}
