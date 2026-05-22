# Design dokument

## Architektura

Systém je rozdělený na pět druhů služeb, každá služba běží jako samostatný kontejner
v Docker Compose:

```
  station-1 ┐
  station-2 │
  station-3 ├──> [Mosquitto] ──> [Backend] ──> [PostgreSQL]
  station-4 │        MQTT         FastAPI
  station-5 ┘                        │
                                     └── SSE/REST ──> [Frontend]
```

- **5× simulátor stanice** — každá stanice má vlastní kontejner. Důvod: zadání
  explicitně testuje paralelnost a samostatné kontejnery ji modelují věrně
  (každá stanice má vlastní MQTT spojení, vlastní state machine, padá a
  startuje nezávisle).
- **Mosquitto** — MQTT broker, předepsaný zadáním.
- **Backend (FastAPI)** — jediný MQTT subscriber; vede lifecycle sessions,
  vystavuje REST API a SSE stream. Záměrně jediný proces — viz *State management*.
- **PostgreSQL** — jediné perzistentní úložiště (stanice, sessions, meter
  readings).
- **Frontend (React SPA)** — tři obrazovky, čte REST a poslouchá SSE.

**Tech stack.** Backend i simulátory jsou v **Pythonu 3.14** — sdílejí tak MQTT
klienta (`aiomqtt`) a styl async kódu. **FastAPI** kvůli async-first modelu
(MQTT adapter a HTTP server běží ve stejné event loop) a protože zdarma
generuje OpenAPI schéma a Swagger UI na `/docs`. Persistence přes
**SQLAlchemy async + asyncpg**. **PostgreSQL 18** bez rozšíření. Frontend
**React 19 + Vite + Tailwind v4** — standardní SPA stack bez zbytečností.

Vědomý tradeoff ve stacku: backend Docker image je plný **`python:3.14`**, ne
`-slim`. `asyncpg` zatím nemá wheel pro Python 3.14 a kompiluje se ze zdroje,
což vyžaduje C toolchain, který `-slim` nemá. Cena je větší image; alternativa
(downgrade Pythonu na 3.13) mi přišla horší než pár stovek MB navíc.

## Klíčové tradeoffs

### MQTT topic struktura

**Zvolil jsem** hierarchii `cpo/v1/stations/{id}/events/{typ}` pro zprávy
stanic a `cpo/v1/stations/{id}/commands/{typ}` pro příkazy backendu. Backend
subscribuje wildcard `cpo/v1/stations/+/events/+`.

**Proč:** prefix `v1` umožní budoucí `v2` vedle stávajícího bez breaking
change. Oddělení `events` / `commands` zpřehledňuje, kdo je producent. Plná
hierarchie navíc umožní budoucí shared subscriptions (`$share/...`) při škále.

**Zvažoval jsem** plochou strukturu `stations/+/heartbeat`. Je kratší, ale bez
verze a bez čistého oddělení směru toku — pro doménu, kde se protokol bude
vyvíjet, mi přišla krátkozraká.

### QoS levels (pro heartbeat / status / meter / commands)

**Zvolil jsem:** heartbeat **QoS 0**, status **QoS 1**, meter **QoS 1**,
commands **QoS 2**, boot a LWT **QoS 1**.

**Proč:** heartbeat chodí často (30 s) a ztráta jednoho nic neznamená — offline
detekce zachytí až trvalý výpadek, QoS 0 stačí. Status a meter jsou důležité a
idempotentní (meter se navíc deduplikuje v aplikaci přes `(tx_id, ts)`), proto
QoS 1 „aspoň jednou". Commands jdou na QoS 2 „přesně jednou" — dvojí doručení
`start_charging` by znamenalo dvojí účtování.

**Zvažoval jsem** QoS 2 i pro meter. Zamítl jsem to: QoS 2 má vyšší režii a
aplikační deduplikace problém duplicit stejně řeší levněji.

### Retained messages

**Zvolil jsem** retained pro `events/status` a `events/boot`; **ne** retained
pro `events/heartbeat`, `events/meter` a `commands/*`.

**Proč:** nový subscriber nebo restartovaný backend díky retained status/boot
dostane aktuální stav každé stanice okamžitě, aniž by stanice musela
republikovat. Heartbeat je časově citlivý — retained starý heartbeat by mátl.
Meter je proud dat. Retained command by se po reconnectu znovu vykonal.

### Realtime FE updates (polling / WebSocket / SSE / MQTT-WS)

**Zvolil jsem** Server-Sent Events — backend vystavuje `GET /api/stream/events`,
frontend ho čte přes `EventSource`.

**Proč:** tok dat je čistě jednosměrný (server → prohlížeč), na to je SSE
ideální — je HTTP-native, má vestavěný auto-reconnect a nepotřebuje zvláštní
handshake jako WebSocket. Akce uživatele (Start/Stop) jdou běžným REST POSTem,
obousměrný kanál není potřeba.

**Zvažoval jsem** polling (jednoduchý, ale buď zpožďuje, nebo zbytečně zatěžuje),
WebSocket (overkill pro jednosměrný tok) a MQTT-over-WebSocket přímo do
prohlížeče (vázal by frontend na broker a obešel backend jako autoritu).

Odchylka oproti původnímu návrhu: během implementace jsem přidal pátý SSE event
`heartbeat`. Dashboard nemá polling a bez něj by se „Last heartbeat" u nečinné
stanice po načtení nikdy neaktualizoval.

### DB schema (jedno úložiště vs. SQL + time-series)

**Zvolil jsem** jediné úložiště — čistý PostgreSQL, tři tabulky (`stations`,
`sessions`, `meter_readings`).

**Proč:** meter readings jsou sice time-series, ale objem je malý — 5 stanic ×
5s tick je řádově ~86 tisíc řádků za den. To čistý Postgres s indexy zvládá bez
problémů. Samostatná time-series DB (InfluxDB, TimescaleDB) by přidala službu,
provozní složitost a druhý konzistenční model výměnou za výkon, který tady není
potřeba.

**Zvažoval jsem** SQL pro metadata + time-series DB pro meter. Pro MVP této
velikosti je to over-engineering.

### State management (in-memory / Redis / jen DB)

**Zvolil jsem** jako zdroj pravdy jen databázi. Tabulka `stations` navíc nese
úzký cache sloupec (`current_status`, `last_heartbeat`, `last_meter_wh`), aby
dashboard nemusel agregovat z `meter_readings`. Frontend nemá globální store —
každá obrazovka má vlastní custom hook (`useStationsLive`, `useStationDetail`,
`useStationSessions`).

**Proč:** backend je jednoprocesový, takže žádný sdílený stav mimo DB nevzniká.
Redis by zaváděl další službu bez užitku. Na frontendu jsou tři obrazovky bez
sdíleného stavu — Redux/Zustand by byl zbytečný aparát.

**Zvažoval jsem** in-memory cache stavu stanic v backendu. Zamítl jsem to:
přežil by restart hůř než DB a přinesl by riziko nekonzistence.

### Error handling (retry / DLQ / circuit breaker)

**Zvolil jsem** lehkou variantu: idempotentní `POST /start` (stejné
`transaction_id` vrátí existující session místo založení nové), exactly-once na
úrovni MQTT příkazů (QoS 2) a perzistentní MQTT spojení stanic
(`clean_session=False` se stabilním `client_id`), takže broker bufferuje QoS
1/2 zprávy přes krátký výpadek a doručí je po reconnectu.

**Proč:** to pokrývá reálné chybové scénáře MVP — krátký výpadek sítě, dvojí
odeslání příkazu — bez infrastruktury navíc.

**Zvažoval jsem** retry frontu, dead-letter queue a circuit breaker. Pro 5
stanic na interní síti je to předčasná složitost; zmiňuju je jako směr, kam by
řešení rostlo při větší škále.

## Co bych udělal jinak s víc časem

- **Ohraničit SSE fronty.** Broadcaster drží per-klient neohraničenou
  `asyncio.Queue` — pomalý nebo mrtvý prohlížeč by rostl v paměti až do
  odpojení. Dal bych frontě strop a drop policy.
- **Perzistentní metr simulátoru, nebo clamp.** Kumulativní metr simulátoru je
  in-memory a po restartu se resetuje na 0; session přes restart pak dá záporné
  `total_kwh` (formule se aplikuje bez clampu). Buď metr perzistovat, nebo
  výsledek ořezat na ≥ 0.
- **Izolovaně otestovat periodic offline detektor.** Dnes E2E test pokrývá jen
  LWT cestu — kill kontejneru vždy vyvolá LWT a ten produkuje stejný stav jako
  pomalá heartbeat-timeout větev. Detektor bych otestoval s uměle potlačeným LWT.
- **Manuálně otestovat stránkování historie.** Tlačítko „Load more" je zatím
  jen code-reviewed — vyžaduje >50 sessions, na což ruční test nedošel.
- **Opravit popisek grafu.** Graf na detailu nečinné stanice je nadepsaný
  „last 5 min", ale ukazuje poslední dokončenou session bez ohledu na její
  stáří — popisek je nepřesný.

## Slabá místa současného řešení

- **Když spadne MQTT broker.** Stanice se připojují s `clean_session=False` a
  stabilním `client_id`, takže broker po reconnectu doručí bufferované QoS 1/2
  zprávy a díky persistenci si drží retained status/boot přes vlastní restart.
  Co se ztratí, jsou heartbeaty (QoS 0) během výpadku — ale to offline detekce
  zachytí korektně. Slabina: po dobu výpadku brokeru nejede nic a backend nemá
  vlastní reconnect-with-backoff dotažený do ideální podoby.
- **Když databáze přijde o čas (NTP).** Heartbeat `ts` je čas přijetí zprávy
  **backendem**, ne čas stanice — drift hodin samotné stanice tedy offline
  detekci neovlivní. Zranitelný je čas backendu: je jediným zdrojem času pro
  všechny timeouty, takže jeho skok by posunul offline detekci i časy sessions.
- **Když se stanice připojí dvakrát se stejným ID.** Mají shodný MQTT
  `client_id`, takže broker staršího klienta odpojí (chování dané MQTT
  specifikací). Backend ale dvě fyzické stanice se stejným ID nijak nerozliší —
  obě publikují na tytéž topicy a na řádku stanice platí „poslední vyhrává".
  Detekci duplicitních ID systém nemá.
- **Záporné `total_kwh`** je možné u session, která přežije restart simulátoru
  (viz *Co bych udělal jinak*).
- **Periodic offline detektor je ověřený jen review, ne E2E** — kill kontejneru
  vždy spustí LWT, který produkuje identický pozorovatelný stav, takže
  heartbeat-timeout větev se v testu nikdy samostatně neprojeví.
- **Boot handler je fakticky jen code-reviewed.** Hodnoty boot zprávy jsou
  shodné s úvodním DB seedem (oba pocházejí ze stejné konfigurace), takže boot
  handler na řádku stanice neprodukuje pozorovatelnou změnu. Seed a boot jsou
  v MVP částečně redundantní — seed nastartuje dashboard dřív, než se stanice
  připojí, boot je reálná registrační cesta.
- **SSE broadcaster je proces-local.** Nasazení backendu s víc workery by
  potřebovalo sdílený bus (např. Redis pub/sub) — dnešní řešení je výhradně
  jednoprocesové. `status_changed` se navíc emituje ze dvou míst (handler
  statusu i offline detektor) a jejich neduplicita stojí na filtru
  `WHERE current_status != 'Offline'`.
- **Fault padne i na „spolehlivé" stanice.** Stanice s `FAULT_PROBABILITY=0.02`
  přes mnoho ticků čas od času faultne — to je očekávané pravděpodobnostní
  chování, ne chyba, ale je dobré ho mít na paměti při čtení historie.
- **Toolchain detail:** ruff má `target-version` přibitý na `py313`, ne `py314`.
  Pod `py314` by formatter mohl emitovat PEP 758 syntaxi (`except A, B:`);
  běhové prostředí je 3.14 nezávisle na tomto nastavení, jde čistě o to, jakou
  syntaxi smí formatter generovat.

## Čas

| Oblast | Hodiny |
|---|---|
| Analýza zadání + hrubá architektura | 4 |
| Setup izolovaného dev prostředí | 4 |
| Upřesnění architektury + Claude Code setup (agenti, verifikační workflow) | 4,5 |
| Implementace fáze 1–7 (broker, simulátor, backend, frontend, Compose) | 14 |
| Závěrečný E2E test a dokumentace | 4,5 |
| **Celkem** | **31** |

## Spolupráce s AI asistentem

Použil jsem **Claude Code** v agentic režimu. Práce probíhala **fázi po fázi**
podle pevného implementačního pořadí (`docs/architektura.md` §11): Mosquitto →
simulátor → doménová vrstva → MQTT adapter → REST/SSE → frontend → finalizace
Compose → E2E test → dokumentace. Každá fáze v samostatné session. Důležitý stav držen v souborech, ne v paměti session — orchestrace přes víc
sessions.

Každá fáze byla plánovaná dopředu (plan mode) a po implementaci ověřená
**dvoustupňově**: subagent `e2e-runner` provedl nezávislé posouzení shody
implementace s plánem a pak spustil deterministický verifikační skript
(`scripts/verify/phase-N-*.sh`), který testuje reálně běžící systém. Samy verifikační skripty procházely vývojem.