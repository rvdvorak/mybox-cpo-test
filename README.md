# Mini CPO Platform

Zjednodušená platforma pro správu flotily **5 EV nabíjecích stanic**. Stanice
jsou simulované; komunikace mezi platformou a stanicemi probíhá přes MQTT broker.

```
[5× simulátor stanice] → [Mosquitto MQTT] → [Backend] → [Frontend dashboard]
                                                ↓
                                           [PostgreSQL]
```

Backend subscribuje MQTT zprávy stanic, vede lifecycle charging sessions, vystavuje
REST API a real-time SSE stream. Frontend je SPA s živým dashboardem (bez F5).
Celý systém startuje jediným `docker compose up`.

**Stack:** Python 3.14 + FastAPI (backend, simulátory), Eclipse Mosquitto 2.1
(broker), PostgreSQL 18 (DB), React 19 + Vite + Tailwind v4 (frontend).
Architektonická rozhodnutí a tradeoffs viz [`DESIGN.md`](DESIGN.md).

## Setup

Prerekvizity:

- **Docker** a **Docker Compose v2** — příkaz `docker compose` (ne starší
  `docker-compose`).
- Volitelně pro sekci [Test](#test): `curl` a `mosquitto_sub` (balík
  `mosquitto-clients`) na hostu.

Kroky:

```bash
git clone https://github.com/rvdvorak/mybox-cpo-test
cd mybox-cpo-test
cp .env.example .env
```

`.env` není potřeba editovat — výchozí hodnoty fungují out-of-the-box. Soubor
existuje proto, aby šly hodnoty (cena za kWh, porty, heartbeat timeout) přepsat
bez zásahu do `docker-compose.yml`.

## Run

```bash
docker compose up --build      # popředí, logy v terminálu
docker compose up -d --build   # detached (na pozadí)
```

`--build` je potřeba při prvním spuštění. Compose má nastavené healthchecky a
`depends_on: condition: service_healthy`, takže služby startují ve správném
pořadí (mosquitto → db → backend → frontend → 5× stanice) a stack naběhne sám.

**První build trvá déle** — backend image kompiluje `asyncpg` ze zdroje (Python
3.14 zatím nemá hotový wheel), backend healthcheck proto má `start_period: 40s`.

Stav služeb (čekej na `healthy`):

```bash
docker compose ps
```

URL po naběhnutí:

| Služba | URL |
|---|---|
| Frontend dashboard | <http://localhost:8080> |
| REST API | <http://localhost:3000/api> |
| Swagger UI (interaktivní API dokumentace) | <http://localhost:3000/docs> |

Vypnutí: `docker compose down` (data DB přežijí), `docker compose down -v`
(smaže i volumes).

## Test

Scénáře pokrývají hard requirements ze zadání. Předpokládají běžící stack
(`docker compose ps` → všechny služby `healthy`). Stanice po startu krátce
ukazují `Offline`, než backend zpracuje retained status z brokeru — počkej, až
přejdou na `Available`.

Barevné kódování statusu v UI: `Available` zelená, `Charging` modrá,
`Preparing`/`Finishing` přechodové, `Faulted` červená, `Offline` šedá.

### 1. Start/stop charging session přes UI

1. Otevři <http://localhost:8080> — dashboard ukazuje tabulku **5 stanic**
   (ST-001 až ST-005) se sloupci Station ID, Status, Power, Last heartbeat.
2. Klikni na řádek `ST-001` → otevře se detail `/stations/ST-001` (hlavička
   stanice + tlačítko **Start**).
3. Klikni na **Start**. **Bez obnovení stránky** sleduj přechod statusu:
   `Available` → `Preparing` (~2 s) → `Charging`. Objeví se panel aktivní
   session (transaction ID, čas startu, energie, výkon).
4. Na detailu nabíjející stanice je **živý graf** (Recharts) — každých ~5 s
   přibude nový bod (meter reading), bez F5.
5. Otevři dashboard `/` ve druhé záložce — řádek `ST-001` tam ukazuje
   `Charging` taky bez F5 (SSE doručuje update na všechny otevřené obrazovky).
6. Na detailu klikni na **Stop** → status přejde `Charging` → `Finishing` →
   `Available`, panel session zmizí.
7. Klikni na **View session history →** (`/stations/ST-001/sessions`) — právě
   ukončená session je v tabulce: čas startu/konce, délka, energie (kWh), cena
   (CZK), `end_reason = completed`.

### 2. Start/stop charging session přes API

```bash
# Start — vrátí 202 s vygenerovaným transaction_id
curl -X POST http://localhost:3000/api/stations/ST-001/start \
  -H 'Content-Type: application/json' -d '{}'
```

```json
{
  "transaction_id": "bc3d01ed-eef2-4265-9fba-442d5b504985",
  "issued_at": "2026-05-22T13:44:32.568616Z",
  "message": "Start command published to station"
}
```

```bash
# Stop — vrátí 202
curl -X POST http://localhost:3000/api/stations/ST-001/stop \
  -H 'Content-Type: application/json' -d '{}'
```

```json
{ "issued_at": "2026-05-22T13:44:43.845941Z", "message": "Stop command published to station" }
```

Stop na stanici bez aktivní session vrátí **409**:

```json
{ "error": "No active session to stop", "code": "NO_ACTIVE_SESSION" }
```

Historie sessions (po dokončení session):

```bash
curl http://localhost:3000/api/stations/ST-001/sessions
```

```json
{
  "sessions": [
    {
      "transaction_id": "bc3d01ed-eef2-4265-9fba-442d5b504985",
      "station_id": "ST-001",
      "start_time": "2026-05-22T13:44:34.097000Z",
      "end_time": "2026-05-22T13:44:43.851000Z",
      "duration_seconds": 9,
      "start_meter_wh": 205,
      "end_meter_wh": 235,
      "total_kwh": 0.03,
      "total_cost": 0.17,
      "end_reason": "completed"
    }
  ],
  "total": 1
}
```

**Alternativa bez `curl`:** FastAPI generuje interaktivní **Swagger UI** na
<http://localhost:3000/docs> — všech 5 REST endpointů lze vyzkoušet přímo
z prohlížeče přes tlačítko „Try it out". (Není to požadavek zadání; FastAPI
ho poskytuje zdarma bez kódu navíc.)

### 3. MQTT komunikace

Odposlech provozu na brokeru z hostu:

```bash
mosquitto_sub -h localhost -t '#' -v          # vše
mosquitto_sub -h localhost -t 'cpo/v1/#' -v   # jen provoz stanic
```

V outputu uvidíš heartbeaty (každých 30 s), status změny a meter values
(během charging session každých 5 s) na topicích
`cpo/v1/stations/{id}/events/*`. Po odeslání Start/Stop přes UI nebo API
uvidíš i příkazy na `cpo/v1/stations/{id}/commands/*`.

### 4. Offline detekce

```bash
docker compose kill station-4
```

Status `ST-004` v UI (dashboard i detail) přejde na `Offline` **prakticky
okamžitě**, bez F5 — stanice se odpojí přes MQTT Last Will (LWT), resp.
graceful shutdown. Periodic heartbeat-timeout check (90 s) je jen **záloha**
pro případ, kdy LWT nedorazí — za normálních okolností se na něj nečeká.

Návrat stanice online:

```bash
docker compose start station-4
```

Po chvíli se `ST-004` vrátí na `Available`.

### 5. Fault scénář

Stanice `ST-003` má `FAULT_PROBABILITY=0.30` (30% šance na fault při každém 5s
meter ticku). Ostatní stanice mají `0.02` — fault je tam vzácný.

1. Otevři detail `ST-003`, klikni **Start**, sleduj nabíjení.
2. S ~30% šancí na každý tick stanice přejde do `Faulted` (červený badge), bez
   F5. Session se uzavře s `end_reason = faulted` (viz historie session).
3. Pokud fault během session nepadne, klikni **Stop** a **Start** znovu —
   pravděpodobnostní jev, do pár pokusů fault padne.
4. Faulted stanice se po ~30 s (`FAULT_RECOVERY_SEC`) sama vrátí na `Available`.

## Architecture

Detailní architektura — service decomposition, MQTT topic struktura, QoS,
DB schema, REST/SSE kontrakt — je v [`docs/architektura.md`](docs/architektura.md).
Klíčová rozhodnutí a jejich tradeoffs shrnuje [`DESIGN.md`](DESIGN.md).

Doplňkové materiály:

- [`docs/phase-8-ui-checklist.md`](docs/phase-8-ui-checklist.md) — manuální QA
  checklist pro proklik UI v prohlížeči.
- [`scripts/verify/`](scripts/verify/) — operační verifikační skripty (testují
  běžící systém přes `docker compose`, `curl`, `mosquitto_sub`, `psql`); spustit
  lze `scripts/verify/phase-8-e2e.sh` pro end-to-end kontrolu celého stacku.
