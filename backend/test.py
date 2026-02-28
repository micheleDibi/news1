"""
Script di test: esegue la pipeline completa una volta sola e poi termina.
Uso: python test.py (dalla cartella backend/)
"""
from app.sender import run_news_pipeline
from datetime import datetime

if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"  Pipeline di test - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    try:
        run_news_pipeline()
    except Exception as e:
        print(f"\nErrore durante la pipeline: {str(e)}")

    print(f"\n{'='*50}")
    print(f"  Pipeline terminata - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
