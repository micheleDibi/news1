/**
 * Resolve hook per `node --test` con --experimental-strip-types.
 *
 * I moduli in src/ importano i fratelli senza estensione (`from './slug'`),
 * perche' tsc con moduleResolution "node" rifiuta gli specificatori `.ts`
 * (TS5097). Node in ESM invece non aggiunge estensioni da solo: senza questo
 * hook quegli import falliscono con ERR_MODULE_NOT_FOUND.
 *
 * Interviene solo quando la risoluzione normale fallisce, solo per
 * specificatori relativi importati da un file .ts e privi di estensione:
 * prova `<spec>.ts` e poi `<spec>/index.ts`. Nessuna dipendenza.
 */
export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context);
  } catch (errore) {
    const relativo = specifier.startsWith('./') || specifier.startsWith('../');
    const daTs = typeof context.parentURL === 'string' && context.parentURL.endsWith('.ts');
    if (errore?.code !== 'ERR_MODULE_NOT_FOUND' || !relativo || !daTs || /\.[cm]?[jt]s$/.test(specifier)) {
      throw errore;
    }
    for (const candidato of [`${specifier}.ts`, `${specifier}/index.ts`]) {
      try {
        return await nextResolve(candidato, context);
      } catch {
        // prova il candidato successivo
      }
    }
    throw errore;
  }
}
