// Caricato con `node --import`: registra il resolve hook per i test.
import { register } from 'node:module';

register('./risolutore-ts.mjs', import.meta.url);
