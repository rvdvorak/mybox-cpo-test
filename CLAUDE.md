# Mini CPO Platform — Project Context

Greenfield projekt podle `TASK.md`. **Architektura je zafixovaná** — viz `@docs/architektura.md`. Žádné odchylky bez explicitní diskuze v plan mode.

## Stack (závazné, neproměňovat)

- Backend: **Python 3.14 + FastAPI ^0.136 + aiomqtt ^2.4 + SQLAlchemy ^2.0 async + asyncpg ^0.30**
- DB: **PostgreSQL 18-alpine** (čistá, žádné TimescaleDB v MVP)
- Frontend: **React ^19.2 + Vite ^8.0 + TypeScript ^5.9 + Tailwind ^4.3 + Recharts ^3.8 + @tabler/icons-react ^3.44 + react-router-dom ^7** (pragmatická TS strictness, ne strict mode)
- MQTT broker: **Eclipse Mosquitto 2.1-alpine**
- Simulátor: **Python 3.14 + aiomqtt ^2.4** (konzistence s backendem)
- Docker base image (backend): **`python:3.14`** — plný image, **NE `-slim`**. `asyncpg ^0.30` zatím nemá `cp314` wheel a kompiluje se ze zdroje; `-slim` nemá C toolchain ani libc hlavičky a build selže. Simulátor má jen pure-Python závislost (`aiomqtt`), jeho image proto zůstává `python:3.14-slim`.
- Toolchain: **ruff ^0.15** (Python), **prettier ^3.8** (TS/JSX/CSS)

## Pravidla práce

1. **Plan mode first.** Před každou nontriviální změnou (více než jeden soubor / více než ~30 řádků kódu) prezentuj plán k mému schválení. Žádné improvizace.
2. **Pokud diff začne odbíhat od schváleného plánu, STOP a vrať se k uživateli.** Nedoplňuj scope za běhu.
3. **Žádné bonusy z TASK.md sekce "Bonus".** Out-of-scope pro MVP: OCPP 1.6 implementace, advanced analytics dashboard, automated testy (unit ani integration), authentication, per-station rate limiting, pricing tarify (peak/off-peak), Grafana/Prometheus monitoring.
4. **Komunikace v češtině**, kód a inline komentáře v angličtině, commit messages v angličtině.
5. **Žádné mass refactory.** Změny jsou inkrementální, malé, commitnuté.
6. **Žádné `git commit` ani `git add` z tvé strany.** Po dokončení každé fáze (nebo logického milestone) zastav a oznam *"Fáze X hotová, k inspekci"*. Commit udělá uživatel ručně. Ty jen pracuješ na změnách — staging a committing je uživatelská odpovědnost a součást review vrstvy.

## Konvence

- **Code style Python**: ruff format + ruff check. PEP 8. Type hints na public API. `async def` všude, kde to dává smysl.
- **Code style TypeScript**: prettier defaults. Pragmatická strictness — `strict: false`, jen `noImplicitAny` a `strictNullChecks`. Type definitions píšeš pouze pro API contract shapes (architektura 7), SSE event payloads (architektura 7.6) a props interfaces. Zbytek inference.
- **File naming**: snake_case pro Python, kebab-case pro CSS/HTML, PascalCase pro React komponenty (`StationCard.tsx`), camelCase pro utility soubory v TS/JS (`apiClient.ts`, `formatDuration.ts`).

## Implementační pořadí

Postupuj fázi po fázi podle `@docs/architektura.md` sekce 11 (Implementační pořadí):

1. Mosquitto config + minimalistický `docker-compose.yml`
2. Simulátor (state machine + instance)
3. Backend doménová vrstva + DB schema
4. Backend MQTT adapter + DB persistence
5. Backend REST + SSE
6. Frontend (3 obrazovky)
7. Docker Compose finalizace (healthchecks, depends_on, volumes)
8. End-to-end test a ladění
9. README + DESIGN.md

**Mezi fázemi:** verifikace přes `e2e-runner` (viz níže) → commit → `/clear` pro čistý kontext. Důležitý stav je v souborech, ne v paměti.

## Verifikace mezi fázemi

Každá fáze končí deterministickou verifikací přes subagenta `e2e-runner` — povinný krok podle tohoto pravidla.

- **Verifikační skript se píše jako poslední úkol fáze.** `scripts/verify/phase-N-*.sh` vzniká až po implementaci fáze N — nikdy předem, nikdy jako stub. Během implementace může dojít ke schválené odchylce od architektury; skript psaný na konci ji reflektuje. Napsání skriptu je **explicitní položka implementačního plánu** fáze (pravidlo 1).
- **Povinný poslední krok každé fáze:** po napsání verify skriptu dispatchni subagenta `e2e-runner` (Task tool, `subagent_type: e2e-runner`) a předej mu číslo fáze + schválený předimplementační plán. Subagent provede stage 1 (nezávislé posouzení shody implementace s plánem) → stage 2 (deterministický E2E test) a vrátí `STATUS: PASS | FAIL | DEVIATION | ERROR`. Teprve s jeho verdiktem ohlas *"Fáze X hotová, k inspekci"* + výsledek.
- Subagent na `FAIL`/`DEVIATION` jen reportuje — neopravuje (pravidlo 2). Vrať se k uživateli.
- **Uživatel verdikt posoudí** a provede manuální commit, nebo intervenci. `e2e-runner` nikdy nestageuje/necommituje — verifikace je brána *před* manuálním commitem uživatele (pravidlo 6).
- `scripts/verify/` jsou **operační verifikační skripty, NE automatizovaná test suite** — cvičí běžící systém (docker compose, mosquitto, curl, psql) a zasévají README sekci "Test" (Fáze 9). Hlavní vlákno verifikaci nespouští inline — vždy deleguje na subagenta.
- Manuální re-run po opravě: `/verify-phase N`.

## Co NEDĚLAT

- Nepouštět se do bonusů (OCPP, advanced dashboard, tests, auth, rate limiting, tarify, monitoring) — viz Pravidla bod 3.
- **Negenerovat automated testy.** Doménová vrstva (architektura sekce 5.1) je strukturně testovatelná, ale testy se v MVP nepíšou. Manual test scenarios přijdou do README ve Fázi 9 (architektura sekce 11 krok 9). *Pozn.: `scripts/verify/` (operační verifikační skripty psané na konci každé fáze) nejsou test suite — viz sekce "Verifikace mezi fázemi".*
- Nepřidávat dependencies bez vysvětlení (proč zrovna ta knihovna, jaká byla alternativa).
- Nesahat na `.env` — jen `.env.example`. Uživatel si vyrobí `.env` ručně.
- Nepoužívat `tailwind.config.js` — Tailwind v4 používá CSS-first config přes `@import "tailwindcss"` a `@theme` direktivu v hlavním CSS souboru. Tohle je častá chyba z training dat.
- **Neimportovat state management library** (Redux, Zustand, Jotai, Recoil) — frontend používá jen per-view custom React hooks (architektura sekce 8.6). Pro 3 obrazovky bez sdíleného stavu je `useState` + custom hooks správná granularita.
- **Neenforce-ovat strict TypeScript.** `strict: false` v `tsconfig.json`, žádné `noImplicitReturns`, žádné generics nad minimum, žádné branded types, žádné conditional types. TS je pragmatický kontrakt-enforcement layer, ne typovací cvičení. Když typování konkrétního místa trvá víc než 15 minut, použij `any` s `// TODO: tighten type` komentářem.
- Nepublikovat MQTT zprávy z backendu mimo `cpo/v1/stations/{id}/commands/*` topics (architektura sekce 3.1, 4.3).
- Negenerovat `STATION_ID` v formátu jiném než `ST-XXX` (architektura sekce 10.2).

## Obsah README

README.md je hard requirement z `TASK.md`. Píše se ve Fázi 9 (architektura sekce 11). Musí obsahovat:

- **Setup**: prerequisites (Docker, Docker Compose), klonování repa, `cp .env.example .env`.
- **Run**: jediný `docker compose up` (případně `-d` flag), očekávané URLs (frontend na `http://localhost:8080`, backend API na `http://localhost:3000`).
- **Test**: manual test scenarios pro každý hard requirement:
  - Jak vyzkoušet start/stop session přes UI (klik na stanici → Start → sledovat status změnu → Stop).
  - Jak vyzkoušet start/stop session přes API (`curl` examples s expected response).
  - Jak ověřit MQTT komunikaci přes `mosquitto_sub -h localhost -t '#' -v`.
  - Jak ověřit offline detection (zastavit jeden simulator container → po 90 s status `Offline` v UI).
  - Jak ověřit fault scenarios (station-3 má `FAULT_PROBABILITY=0.30` z architektury 10.2).
- **Architecture**: krátký odkaz na `docs/architektura.md`, žádné duplikování obsahu.

Tón: technický, věcný, instrukční. Žádný marketing, žádné "vítejte v našem projektu". Cíl: recruiter v MyBox musí být schopen postupovat krok po kroku a všechno mu funguje.

## Tón DESIGN.md (až přijde čas)

DESIGN.md bude psaný **až nakonec** (ve Fázi 9 z architektury sekce 11), buď přes subagent `design-doc-writer`, nebo manuálně. Pravidla pro tón:

- Sebekritická reflexe vlastního řešení, ne strategický rámec pro firmu.
- Identifikace tradeoffs (zvolil X, zvažoval Y, slabina je Z).
- Technické položky na úrovni mého řešení, ne na úrovni firmy.
- **NESMÍ obsahovat**: strategický plán pro produkční nasazení/škálování firmy, "first 90 days plan", "jak vidím vaši situaci", framework pro insourcing cloudu, doporučení pro tým.
