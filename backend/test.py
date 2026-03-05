"""
Script di test: riprende gli interpelli con stato 'classified',
esegue enrichment metadati e generazione articolo.
Uso: python test.py (dalla cartella backend/)
"""
from app.interpelli import enrich_all_classified, generate_articles_for_pending
from datetime import datetime

if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"  Enrichment + Articoli - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    try:
        print("--- STEP 1: Enrichment metadati (classified -> enriched) ---")
        enriched = enrich_all_classified()
        print(f"Arricchiti: {enriched}\n")

        print("--- STEP 2: Generazione articoli (enriched -> completed) ---")
        articles = generate_articles_for_pending()
        print(f"Articoli generati: {articles}\n")

    except Exception as e:
        print(f"\nErrore: {str(e)}")

    print(f"\n{'='*50}")
    print(f"  Terminato - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
