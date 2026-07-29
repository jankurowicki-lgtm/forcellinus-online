# Forcellinus — Lexicon Totius Latinitatis

Statyczna aplikacja PWA wyświetlająca wewnątrz aplikacji artykuły wydobyte z
publicznego OCR Internet Archive. W czasie działania nie łączy się z Linguax ani
z Internet Archive; GitHub Actions buduje statyczne, dzielone pliki JSON.

## Budowanie

```bash
python scripts/build_dictionary.py
python tests/test_dictionary.py
python -m http.server -d public 8000
```

Importer pobiera wskazane tomy, usuwa wyłącznie oczywisty szum układu strony,
wykrywa nagłówki artykułów i zapisuje indeksy oraz artykuły w małych shardach.
Status `full` jest nadawany tylko po wykryciu co najmniej 20 000 artykułów i
potwierdzeniu wszystkich sześciu haseł testowych; w przeciwnym razie interfejs
uczciwie opisuje wynik jako bazę próbną.

## Źródła

- [Tom 1 — Internet Archive](https://archive.org/details/totiuslatinitati01forc)
- [Tom 2 — Internet Archive](https://archive.org/details/totiuslatinitati02forc)

Tekst jest automatycznym OCR i może zawierać błędy rozpoznania.
