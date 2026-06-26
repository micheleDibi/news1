from app.scrapers.root_discovery import RootDiscovery, extract_fonte_links_from_html, unique_urls


def test_extract_fonte_links_filters_and_deduplicates():
    html = """
    <html><body>
      <a href="/it/opportunita_2021_2027/programma-a/">Programma A</a>
      <a href="https://opencoesione.gov.it/it/opportunita_2021_2027/programma-a/">Programma A dup</a>
      <a href="/it/opportunita_2021_2027/programma-b">Programma B</a>
      <a href="mailto:test@example.com">Mail</a>
      <a href="https://example.com/outside">Outside</a>
      <a href="/it/opportunita_2021_2027/programma-c#sezione">Programma C</a>
    </body></html>
    """

    links = extract_fonte_links_from_html(
        html,
        root_url="https://opencoesione.gov.it/it/opportunita_2021_2027/",
    )

    urls = unique_urls(links)
    assert urls == [
        "https://opencoesione.gov.it/it/opportunita_2021_2027/programma-a",
        "https://opencoesione.gov.it/it/opportunita_2021_2027/programma-b",
        "https://opencoesione.gov.it/it/opportunita_2021_2027/programma-c",
    ]


def test_extract_fonte_links_uses_fallback_label_when_empty():
    html = """
    <html><body>
      <a href="/it/opportunita_2021_2027/programma-x/">   </a>
    </body></html>
    """
    links = extract_fonte_links_from_html(
        html,
        root_url="https://opencoesione.gov.it/it/opportunita_2021_2027/",
    )

    assert len(links) == 1
    assert links[0].label == "https://opencoesione.gov.it/it/opportunita_2021_2027/programma-x"


def test_root_discovery_uses_source_root_url_from_settings():
    discovery = RootDiscovery()
    assert discovery.root_url.startswith("https://opencoesione.gov.it/")


def test_extract_fonte_links_only_direct_children_of_source_root_url():
    html = """
    <html><body>
      <a href="/it/opportunita_2021_2027/programma-a">Diretto A</a>
      <a href="/it/opportunita_2021_2027/programma-b">Diretto B</a>
      <a href="/it/opportunita_2021_2027/programma-a/dettaglio">Nidificato da escludere</a>
      <a href="/it/opportunita_2021_2027/programma-b/news/2026">Nidificato da escludere</a>
    </body></html>
    """

    links = extract_fonte_links_from_html(
        html,
        root_url="https://opencoesione.gov.it/it/opportunita_2021_2027/",
    )

    assert unique_urls(links) == [
        "https://opencoesione.gov.it/it/opportunita_2021_2027/programma-a",
        "https://opencoesione.gov.it/it/opportunita_2021_2027/programma-b",
    ]
