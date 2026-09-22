# FPL Control Center — instrukcja użytkownika

## Uruchomienie

Uruchom `FPLControlCenter_PL.exe`. Program otwiera się zmaksymalizowany. Górny pasek pokazuje sezon, kolejkę (GW), liczbę wolnych transferów (FT) i bank. Przyciski `−` i `+` zmieniają wartość krokowo; wartość można też wpisać ręcznie. Bank jest podawany w milionach funtów, np. `£0.1m`.

## Synchronizacja konta FPL

1. Wybierz `Sync FPL`.
2. Jeśli potrzebne jest logowanie, wybierz `Open FPL login`.
3. W otwartym oknie Edge zaloguj się ręcznie na oficjalnej stronie FPL.
4. Wróć do programu i wybierz `Retry sync`.

Po udanej synchronizacji program sprawdza skład 15 zawodników, ceny sprzedaży i zakupu, bank, FT, aktualną GW oraz — jeżeli są dostępne — oficjalny skład, kapitana i ławkę. Niepełna synchronizacja nie jest oznaczana jako sukces.

Program działa wyłącznie do odczytu: **nigdy sam nie wykonuje transferów, nie aktywuje chipów i nie zmienia kapitana ani wicekapitana na koncie FPL**.

## Zakładka Squad

`My Squad` pokazuje 15 posiadanych zawodników. `Current XI` przedstawia bieżący skład i ławkę. Po poprawnym wyniku silnika można wybrać `Recommended XI`, aby zobaczyć wyłącznie podgląd rekomendowanego składu, kapitana, wicekapitana i kolejności ławki. Powrót do `Current XI` natychmiast przywraca bieżący widok.

Przycisk `Edit squad` otwiera panel ręcznej korekty składu. Panel można zamknąć przyciskiem `Close`; zamyka się też po przejściu na inną zakładkę. Ręczna zmiana składu nie zastępuje danych konta ani nie tworzy brakujących cen sprzedaży.

Kafelki przy zawodnikach pokazują najbliższe mecze. Procent na kafelku jest `p_5_plus`: prawdopodobieństwem uzyskania co najmniej 5 punktów FPL w danym meczu według bieżącej projekcji. To prognoza, nie gwarancja wyniku.

## Zakładka Analysis

### Run projections

Uruchamia produkcyjne projekcje, gdy nie ma poprawnego pakietu dla wybranego sezonu i GW. Dla zwykłej pracy korzystaj z istniejącego, zgodnego pakietu produkcyjnego, jeśli jest dostępny.

### Run decision engine

Pokazuje rekomendację transferu albo `ROLL FREE TRANSFER`. Przy transferze zobaczysz zawodnika `OUT`, `IN`, cenę sprzedaży i cenę zakupu, a także dostępne dane o zysku projekcyjnym, horyzoncie, koszcie transferu i banku po ruchu.

### Run chip screen

Wyświetla poradę `NO CHIP / ROLL`, `WILDCARD`, `FREE HIT`, `BENCH BOOST` albo `TRIPLE CAPTAIN` tylko dla chipów dostępnych na koncie. To zalecenie informacyjne — program nie aktywuje chipa.

Dokładna analiza Free Hit i Wildcard może trwać długo. Działa asynchronicznie: program pozostaje responsywny, a pasek stanu i Engine log pokazują postęp. Możesz wybrać `Cancel chip analysis`, a później `Retry chip analysis`.

### Run full GW analysis

To zalecany normalny przebieg przed kolejką:

1. zsynchronizuj konto FPL,
2. sprawdź sezon, GW, FT i bank,
3. wybierz `Run full GW analysis`,
4. odczytaj transfer lub ROLL,
5. przejdź do `Recommended XI`, aby sprawdzić XI, kapitana, wicekapitana i ławkę,
6. poczekaj na Chip Screen albo anuluj go, gdy nie jest teraz potrzebny.

Pełna analiza używa tylko zgodnego pakietu produkcyjnego. Nie uruchamia ponownie projekcji V22, gdy poprawny pakiet już istnieje, i nie używa artefaktów tymczasowych.

W czasie pracy widoczne są etapy `VALIDATING`, `PROJECTIONS`, `DECISION`, `RECOMMENDED XI` oraz `CHIP SCREEN`. Po decyzji transfer i Recommended XI są dostępne od razu, nawet gdy Chip Screen nadal liczy. Stan `PARTIAL` oznacza, że wcześniejsze wyniki są poprawne, ale chipy zostały anulowane lub nie ukończyły analizy.

## Zakładka Engine

Zakładka zawiera ustawienia liczby symulacji i seeda oraz techniczny Engine log. Log pomaga zdiagnozować problem, lecz normalna obsługa programu odbywa się w zakładkach Squad i Analysis. Nie udostępniaj logu zawierającego dane konta osobom trzecim.

## Najczęstsze komunikaty

- `LOGIN_REQUIRED` — otwórz FPL login, zaloguj się ręcznie w Edge, potem wybierz Retry sync.
- `CONNECTED` — dane konta przeszły kontrolę kompletności.
- `ERROR · account data incomplete` — synchronizacja zwróciła niepełne dane; uruchom Retry sync i nie traktuj wyniku jako gotowego składu.
- `A matching production projection bundle is required` — uruchom produkcyjne projekcje dla wybranego sezonu/GW albo wybierz poprawną GW.
- `ROLL FREE TRANSFER` — silnik nie rekomenduje transferu w tej kolejce.
- `PARTIAL` — transfer i Recommended XI są dostępne; Chip Screen jest anulowany albo nieudany i można go ponowić.

## Ważne ograniczenie

Dokładna analiza Free Hit/Wildcard może być długa, szczególnie przy dużym zbiorze kandydatów. Nie blokuje to użycia programu: obliczenia działają w tle, postęp jest widoczny, można je anulować lub ponowić, a wynik Decision Engine i Recommended XI pozostają zachowane.
