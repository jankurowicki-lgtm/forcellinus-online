# Forcellinus — Lexicon Totius Latinitatis

Statyczna aplikacja PWA wyświetlająca wewnątrz aplikacji artykuły wydobyte ze
skanów Internet Archive. Workflow GitHub Actions wykonuje własny, równoległy OCR
łacińsko-starogrecki (`lat+grc+eng`), dzięki czemu zachowuje grekę z akcentami i
przydechami. W czasie działania aplikacja nie łączy się z LinguaX ani z Internet
Archive; korzysta wyłącznie ze statycznych, dzielonych plików JSON.

## Budowanie

```bash
python scripts/build_dictionary.py
python tests/test_dictionary.py
python -m http.server -d public 8000
```

Importer usuwa wyłącznie oczywisty szum układu strony, wykrywa nagłówki
artykułów i zapisuje indeksy oraz artykuły w małych shardach.
Status `full` jest nadawany tylko po wykryciu co najmniej 20 000 artykułów i
potwierdzeniu wszystkich haseł testowych; w przeciwnym razie interfejs
uczciwie opisuje wynik jako bazę próbną.

## Źródła

- [Tom 1 — Internet Archive](https://archive.org/details/totiuslatinitati01forc)
- [Tom 2 — Internet Archive](https://archive.org/details/totiuslatinitati02forc)

Tekst jest automatycznym OCR i może zawierać błędy rozpoznania. Test publikacji
wymaga, by artykuł `ratio` zawierał co najmniej formy `νοῦς` i `λόγος`.
