# FPL Prediction & Decision Engine

## Cel projektu

Celem projektu jest stworzenie kompletnego systemu do:

1. predykcji punktów zawodników Fantasy Premier League,
2. szacowania rozkładu możliwych wyników,
3. oceny zawodników w perspektywie wielu Gameweeków,
4. podejmowania decyzji dotyczących składu FPL.

System powinien odpowiadać m.in. na pytania:

- którego zawodnika kupić,
- którego sprzedać,
- czy zachować Free Transfer,
- czy opłaca się wykonać hit -4,
- kto powinien być kapitanem,
- kto powinien znaleźć się na ławce,
- jaka powinna być kolejność ławki,
- kiedy użycie Wildcard / Free Hit / Bench Boost / Triple Captain ma sens,
- jaki skład maksymalizuje expected points w zadanym horyzoncie.

Domyślny planning horizon wynosi 6 Gameweeków.

## Najważniejsza zasada

NIE budujemy jednego modelu:

features -> FPL points

Punkty FPL są zbyt zaszumionym targetem.

System powinien najpierw modelować rzeczywiste zdarzenia piłkarskie i minuty, a następnie przeliczać ich prawdopodobieństwo na punkty FPL.

Docelowy pipeline:

DATA
↓
TEAM STRENGTH
↓
PLAYER TALENT
↓
TACTICAL / ROLE CONTEXT
↓
MINUTES MODEL
↓
MATCH EVENT MODELS
↓
MONTE CARLO
↓
FPL SCORING
↓
PLAYER EV
↓
MULTI-GW OPTIMIZER
↓
RECOMMENDATION

## Główne komponenty

### 1. Team Strength Model
Przewiduje:
- expected goals drużyny,
- expected goals przeciwnika,
- attack strength,
- defence strength,
- clean sheet probability.

Uwzględnia:
- home/away,
- jakość przeciwników,
- time decay,
- xG/xGA,
- wyniki historyczne,
- aktualną siłę zespołu.

### 2. Player Talent Model
Ma rozdzielać PLAYER ABILITY od TEAM ENVIRONMENT.

Historyczne xG/xA zawodnika nie mogą być traktowane jako stałe.

Model musi uwzględniać m.in.:
- jakość poprzedniej drużyny,
- jakość obecnej drużyny,
- udział zawodnika w produkcji ofensywnej zespołu,
- zmianę ligi,
- zmianę klubu,
- zmianę pozycji,
- zmianę trenera,
- zmianę systemu taktycznego.

### 3. Tactical Context
System powinien rozpoznawać istotne regime changes:
- transfer do nowego klubu,
- nowy trener,
- zmiana formacji,
- zmiana pozycji,
- zmiana roli,
- nowe set pieces,
- utrata set pieces,
- kontuzja konkurenta,
- pojawienie się nowego konkurenta.

Stare dane nadal mogą być wykorzystywane do oceny talentu zawodnika, ale ich znaczenie dla aktualnej produkcji powinno zostać odpowiednio zmniejszone.

### 4. Minutes Model
Osobny model przewidujący:
- P(start),
- expected minutes,
- P(60+),
- P(75+),
- P(90),
- prawdopodobieństwo braku występu.

xMins są jednym z najważniejszych elementów całego systemu.

### 5. Event Models
Osobne komponenty powinny przewidywać:
- goal probability,
- assist probability,
- clean sheet probability,
- expected saves,
- penalty save probability,
- card probability,
- defensive contributions,
- bonus/BPS.

### 6. Monte Carlo
System powinien symulować mecze.

Docelowo minimum: 10 000 symulacji fixture.

Output dla zawodnika powinien zawierać:
- EV,
- median,
- P(blank),
- P(return),
- P(5+),
- P(8+),
- P(10+),
- P(15+),
- haul probability.

Zdarzenia w ramach jednego meczu muszą być skorelowane.

### 7. Multi-GW Optimizer
Optimizer podejmuje decyzje na podstawie player projections.

Musi obsługiwać:
- squad constraints,
- formations,
- budget,
- max players per club,
- captain,
- vice-captain,
- bench,
- Free Transfers,
- rolled transfers,
- hits,
- selling prices,
- purchase prices,
- money in bank,
- chips.

Brak transferu jest poprawną decyzją.
Optimizer musi mieć możliwość rekomendacji: ROLL FT.

## Planning horizon

Domyślnie: 6 GW.

Startowa konfiguracja time decay:
- GW+1 = 1.00
- GW+2 = 0.95
- GW+3 = 0.90
- GW+4 = 0.85
- GW+5 = 0.80
- GW+6 = 0.75

Wagi muszą być później zweryfikowane przez backtesting.

## Zasada dotycząca architektury

Projektujemy od początku docelową architekturę.
Nie tworzymy uproszczonego MVP przeznaczonego później do wyrzucenia.
Implementacja odbywa się inkrementalnie, ale każdy element powinien pasować do finalnego systemu.

## Zasada dotycząca złożoności

Nie wybieramy najbardziej skomplikowanego modelu tylko dlatego, że jest skomplikowany.
Każdy zaawansowany model musi zostać porównany z baseline.
Model finalny wybierany jest na podstawie wyników out-of-sample.

## Zasada dotycząca danych

Każda historyczna predykcja musi być wykonana zgodnie z zasadą:
WHAT WAS KNOWN AT PREDICTION TIME?

Żaden feature powstały po deadline danego GW nie może być użyty do jego predykcji.
Data leakage jest błędem krytycznym.

## Język

Kod: English.
Nazwy klas/funkcji/zmiennych: English.
Dokumentacja techniczna: może być English.
Raporty dla użytkownika: Polish.
Rekomendacje FPL: Polish.

## Priorytet projektu

Najważniejsza jest OUT-OF-SAMPLE PREDICTIVE PERFORMANCE,
a nie dopasowanie do danych historycznych.
