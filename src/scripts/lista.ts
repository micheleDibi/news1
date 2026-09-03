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

  const urlDaForm = (): string => {
    const qs = new URLSearchParams();
    for (const [k, v] of new FormData(form) as unknown as Iterable<[string, string]>) {
      if (v !== '') qs.append(k, v);
    }
    // Cambiare un filtro riporta sempre alla prima pagina.
    const s = qs.toString();
    return form.getAttribute('action') + (s ? `?${s}` : '');
  };

  const mostraCaricamento = (attivo: boolean) => {
    if (!indicatore) return;
    indicatore.classList.toggle('hidden', !attivo);
    indicatore.classList.toggle('flex', attivo);
  };

  async function vaiA(url: string, opzioni: { push?: boolean; focus?: boolean } = {}): Promise<void> {
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

      const totale = meta.dataset.totale ?? '';
      if (contatore) contatore.textContent = totale;
      if (stato) stato.textContent = `${totale} risultati, pagina ${meta.dataset.pagina} di ${meta.dataset.pagine}`;

      if (opzioni.push !== false) window.history.pushState(null, '', url);
      if (opzioni.focus) document.getElementById(idLista)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (errore) {
      if ((errore as { name?: string })?.name !== 'AbortError') window.location.assign(url);
    } finally {
      mostraCaricamento(false);
      document.getElementById(idLista)?.removeAttribute('aria-busy');
    }
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    void vaiA(urlDaForm());
  });
  form.addEventListener('change', ritarda(() => void vaiA(urlDaForm()), ATTESA_CONTROLLI));
  form.addEventListener('input', ritarda(() => void vaiA(urlDaForm()), ATTESA_TESTO));

  const reset = document.getElementById('reset-filters');
  reset?.addEventListener('click', (e) => {
    e.preventDefault();
    form.reset();
    for (const campo of form.querySelectorAll('input, select')) {
      if (campo instanceof HTMLInputElement) campo.value = '';
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
    const bersaglio = (evento.target as Element | null)?.closest('#pagination a[href]') as HTMLAnchorElement | null;
    if (!bersaglio) return;
    evento.preventDefault();
    void vaiA(bersaglio.getAttribute('href')!, { focus: true });
  });

  window.addEventListener('popstate', () => {
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
