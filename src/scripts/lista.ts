/**
 * Miglioramento progressivo delle pagine elenco.
 *
 * Senza JavaScript il form fa un GET normale e il server rende la lista filtrata: e'
 * questo che rende i risultati raggiungibili da un crawler. Con JavaScript attivo la
 * navigazione resta senza ricaricare la pagina, ma invece di interrogare PostgREST dal
 * browser e ricostruire le card con innerHTML si chiede al server lo stesso frammento
 * HTML che renderebbe da solo. Un template di card soltanto, e le chiavi anon Supabase
 * spariscono dall'HTML.
 */

interface Opzioni {
  /** id del contenitore della lista, es. 'interpelli-list'. */
  idLista: string;
}

/** Evento emesso sul documento dopo ogni aggiornamento della lista. */
export const EVENTO_AGGIORNATA = 'lista:aggiornata';

const ATTESA_TESTO = 350;
const ATTESA_CONTROLLI = 250;

function ritarda<T extends (...args: never[]) => void>(fn: T, ms: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return (...args: Parameters<T>) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

export function attivaLista({ idLista }: Opzioni): void {
  const form = document.getElementById('filtri') as HTMLFormElement | null;
  if (!form) return;

  const frammento = form.dataset.frammento;
  if (!frammento) return;

  const indicatore = document.getElementById('loading-indicator');
  const contatore = document.getElementById('visible-count');
  const stato = document.getElementById('stato-risultati');
  let inCorso: AbortController | null = null;
  // Percorso su cui il frammento ha senso: i link verso altri percorsi (la
  // paginazione statica di una pagina filtro) restano navigazioni vere.
  const percorsoLista = new URL(form.getAttribute('action') ?? window.location.pathname, window.location.href).pathname;
  const stessoPercorso = (href: string): boolean => new URL(href, window.location.href).pathname === percorsoLista;

  const urlDaForm = (): string => {
    const qs = new URLSearchParams();
    for (const [k, v] of new FormData(form) as unknown as Iterable<[string, string]>) {
      if (v !== '') qs.append(k, v);
    }
    // Cambiare un filtro riporta sempre alla prima pagina.
    const s = qs.toString();
    return form.getAttribute('action') + (s ? `?${s}` : '');
  };
  // Lo stato che la lista mostra, letto dal form: all'avvio quello reso dal
  // server, poi quello dell'ultimo caricamento. Un invio o un cambio che non lo
  // modificano non ricaricano nulla. Il confronto e' col form e non con l'URL
  // della pagina: una pagina filtro (/bandi/regione/…) mostra lo stesso stato
  // di /bandi?regione=…, e premere «Mostra» senza cambiare niente non deve
  // portarla altrove.
  let statoCaricato = urlDaForm();

  const mostraCaricamento = (attivo: boolean) => {
    if (!indicatore) return;
    indicatore.classList.toggle('hidden', !attivo);
    indicatore.classList.toggle('flex', attivo);
  };

  async function vaiA(url: string, opzioni: { push?: boolean; focus?: boolean; sincronizza?: boolean } = {}): Promise<void> {
    inCorso?.abort();
    inCorso = new AbortController();
    const contenitore = document.getElementById(idLista);
    contenitore?.setAttribute('aria-busy', 'true');
    mostraCaricamento(true);

    const query = url.includes('?') ? url.slice(url.indexOf('?')) : '';
    try {
      // Accept esplicito: il middleware converte in Markdown solo se l'header contiene
      // text/markdown, quindi il frammento arriva sempre come HTML.
      const risposta = await fetch(frammento + query, {
        headers: { Accept: 'text/html' },
        signal: inCorso.signal,
      });
      if (!risposta.ok) {
        // 404 di pagina fuori range, 5xx: si lascia decidere al server con una
        // navigazione vera, invece di lasciare la lista congelata senza spiegazioni.
        window.location.assign(url);
        return;
      }

      const documento = new DOMParser().parseFromString(await risposta.text(), 'text/html');
      const nuovaLista = documento.getElementById(idLista);
      const meta = documento.getElementById('frammento');
      if (!nuovaLista || !meta) {
        window.location.assign(url);
        return;
      }

      document.getElementById(idLista)?.replaceWith(nuovaLista);

      const navVecchia = document.getElementById('pagination');
      const navNuova = documento.getElementById('pagination');
      if (navVecchia && navNuova) navVecchia.replaceWith(navNuova);
      else if (navVecchia) navVecchia.remove();
      else if (navNuova) nuovaLista.after(navNuova);

      // Regioni: parti della pagina che dipendono dai filtri, se il frammento le
      // porta (oggi solo i bandi). Il focus resta sull'elemento con la stessa
      // `data-chiave`, cosi' chi naviga da tastiera non lo perde.
      for (const nuova of documento.querySelectorAll<HTMLElement>('[data-regione]')) {
        const vecchia = document.querySelector<HTMLElement>(`[data-regione="${CSS.escape(nuova.dataset.regione ?? '')}"]`);
        if (!vecchia) continue;
        const attivo = document.activeElement as HTMLElement | null;
        const chiave = attivo && vecchia.contains(attivo) ? attivo.dataset.chiave : undefined;
        vecchia.replaceWith(nuova);
        if (chiave) nuova.querySelector<HTMLElement>(`[data-chiave="${CSS.escape(chiave)}"]`)?.focus();
      }
      for (const origine of documento.querySelectorAll<HTMLElement>('[data-testo]')) {
        for (const bersaglio of document.querySelectorAll<HTMLElement>(`[data-testo="${CSS.escape(origine.dataset.testo ?? '')}"]`)) {
          bersaglio.textContent = origine.textContent;
        }
      }
      if (meta.dataset.titolo) document.title = meta.dataset.titolo;

      const totale = meta.dataset.totaleTesto ?? meta.dataset.totale ?? '';
      if (contatore) contatore.textContent = totale;
      if (stato) stato.textContent = `${totale} risultati, pagina ${meta.dataset.pagina} di ${meta.dataset.pagine}`;

      if (opzioni.push !== false && url !== window.location.pathname + window.location.search) window.history.pushState(null, '', url);
      if (opzioni.sincronizza && form) sincronizzaForm(form);
      statoCaricato = urlDaForm();
      if (opzioni.focus) document.getElementById(idLista)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      document.dispatchEvent(new CustomEvent(EVENTO_AGGIORNATA));
    } catch (errore) {
      if ((errore as { name?: string })?.name !== 'AbortError') window.location.assign(url);
    } finally {
      mostraCaricamento(false);
      document.getElementById(idLista)?.removeAttribute('aria-busy');
    }
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const url = urlDaForm();
    if (url === statoCaricato) return;
    void vaiA(url);
  });
  // Solo i controlli con un `name` cambiano la lista: la ricerca dentro una
  // tendina o la casella che apre un pannello no. E se l'URL non cambia non si
  // ricarica niente, cosi' la cronologia non si riempie di voci identiche.
  const conNome = (e: Event): boolean => {
    const bersaglio = e.target as { name?: unknown } | null;
    return typeof bersaglio?.name === 'string' && bersaglio.name !== '';
  };
  const aggiorna = (): void => {
    const url = urlDaForm();
    if (url === statoCaricato) return;
    void vaiA(url);
  };
  const aggiornaControlli = ritarda(aggiorna, ATTESA_CONTROLLI);
  const aggiornaTesto = ritarda(aggiorna, ATTESA_TESTO);
  form.addEventListener('change', (e) => { if (conNome(e)) aggiornaControlli(); });
  form.addEventListener('input', (e) => { if (conNome(e)) aggiornaTesto(); });

  const reset = document.getElementById('reset-filters');
  reset?.addEventListener('click', (e) => {
    e.preventDefault();
    form.reset();
    for (const campo of form.querySelectorAll('input, select')) {
      // Su checkbox e radio `.value` riscrive l'attributo value: dopo un reset
      // ogni scelta partiva vuota e il filtro veniva scartato. Si toglie la
      // spunta, perche' `form.reset()` ripristina quelle rese dal server.
      if (campo instanceof HTMLInputElement && (campo.type === 'checkbox' || campo.type === 'radio')) campo.checked = false;
      else if (campo instanceof HTMLInputElement) campo.value = '';
      if (campo instanceof HTMLSelectElement) campo.selectedIndex = 0;
    }
    form.dispatchEvent(new Event('change'));
    void vaiA(form.getAttribute('action') ?? window.location.pathname);
  });

  // Delega sul documento: la <nav> viene sostituita a ogni caricamento, quindi un
  // listener attaccato direttamente ai link non sopravvivrebbe.
  document.addEventListener('click', (e) => {
    const evento = e as MouseEvent;
    if (evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.button !== 0) return;
    const elemento = evento.target as Element | null;
    const pagina = elemento?.closest('#pagination a[href]') as HTMLAnchorElement | null;
    if (pagina && stessoPercorso(pagina.getAttribute('href')!)) {
      evento.preventDefault();
      void vaiA(pagina.getAttribute('href')!, { focus: true });
      return;
    }
    // Chip, tessere, vista e reset: link veri che portano un altro stato della
    // lista. Dopo il caricamento il form si riallinea all'URL.
    const naviga = elemento?.closest('a[data-naviga][href]') as HTMLAnchorElement | null;
    if (naviga && stessoPercorso(naviga.getAttribute('href')!)) {
      evento.preventDefault();
      void vaiA(naviga.getAttribute('href')!, { sincronizza: true });
    }
  });

  window.addEventListener('popstate', () => {
    // Tornando a un URL di un altro percorso (da /bandi?… alla pagina filtro da
    // cui si era partiti) il frammento della lista non basta: ricarica vera.
    if (window.location.pathname !== percorsoLista) {
      window.location.reload();
      return;
    }
    sincronizzaForm(form);
    void vaiA(window.location.pathname + window.location.search, { push: false });
  });
}

/** Riallinea i controlli del form ai parametri presenti nell'URL (tasto Indietro). */
function sincronizzaForm(form: HTMLFormElement): void {
  const parametri = new URLSearchParams(window.location.search);
  for (const campo of form.querySelectorAll('input[name], select[name]')) {
    const elemento = campo as HTMLInputElement | HTMLSelectElement;
    if (elemento.type === 'checkbox') {
      (elemento as HTMLInputElement).checked = parametri.getAll(elemento.name).includes(elemento.value);
    } else if (elemento.type === 'radio') {
      // Il radio ha un valore fisso: si sceglie, non si riscrive. Senza
      // parametro vale la voce con valore vuoto («Tutti»).
      (elemento as HTMLInputElement).checked = (parametri.get(elemento.name) ?? '') === elemento.value;
    } else {
      elemento.value = parametri.get(elemento.name) ?? '';
    }
  }
  aggiornaProvince(form);
}

/**
 * Select provincia dipendente dalla regione. La mappa arriva da un
 * <script type="application/json">, non piu' da define:vars (che serializzava anche
 * URL e chiave anon di Supabase nell'HTML di ogni pagina).
 */
export function attivaProvinceDipendenti(): void {
  const form = document.getElementById('filtri') as HTMLFormElement | null;
  if (!form) return;
  const regione = form.querySelector('[name="regione"]') as HTMLSelectElement | null;
  regione?.addEventListener('change', () => aggiornaProvince(form));
  aggiornaProvince(form);
}

function aggiornaProvince(form: HTMLFormElement): void {
  const dati = document.getElementById('dati-province');
  const provincia = form.querySelector('[name="provincia"]') as HTMLSelectElement | null;
  const regione = form.querySelector('[name="regione"]') as HTMLSelectElement | null;
  if (!dati || !provincia || !regione) return;

  let mappa: Record<string, Array<{ slug: string; etichetta: string }>> = {};
  try {
    mappa = JSON.parse(dati.textContent || '{}');
  } catch {
    return;
  }

  const selezionata = provincia.value;
  const disponibili = regione.value ? (mappa[regione.value] ?? []) : [];
  provincia.disabled = disponibili.length === 0;
  provincia.innerHTML = '<option value="">Tutte</option>';
  for (const p of disponibili) {
    const opzione = document.createElement('option');
    opzione.value = p.slug;
    opzione.textContent = p.etichetta;
    if (p.slug === selezionata) opzione.selected = true;
    provincia.appendChild(opzione);
  }
}
