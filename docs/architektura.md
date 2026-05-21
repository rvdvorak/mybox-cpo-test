# Architektura — Mini CPO Platform

Tento dokument popisuje technickou architekturu zjednodušené platformy pro správu flotily 5 EV nabíjecích stanic. Funkční požadavky a hodnotící kritéria jsou v `TASK.md`. Tento dokument fixuje technická rozhodnutí, kontrakty zpráv, schéma databáze a implementační pořadí.

---

## 1. Přehled

Systém se skládá z devíti služeb orchestrovaných přes Docker Compose:

```
[5× station-N] ──MQTT──┐
                       ├──> [mosquitto] ──> [backend] ──> [db: postgres]
                                                  │
                                                  └──SSE──> [frontend]
```

- **5× simulátor stanice** (`station-1` … `station-5`) — samostatné kontejnery emulující EV nabíjecí stanice, komunikují přes MQTT.
- **Eclipse Mosquitto** — MQTT broker, předepsaný v zadání.
- **Backend** — REST API + MQTT subscriber + session lifecycle + SSE stream pro frontend.
- **PostgreSQL** — perzistence stanic, session a meter readings.
- **Frontend** — React SPA, dashboard s live updates, detail stanice, historie sessions.

---

## 2. Technologický stack

| Vrstva | Volba | Verze |
|---|---|---|
| Backend jazyk | Python | 3.14 |
| Backend framework | FastAPI | ^0.136 |
| MQTT klient (backend i simulátor) | aiomqtt | ^2.4 |
| Databáze | PostgreSQL | 18-alpine |
| ORM | SQLAlchemy (async) | ^2.0 |
| DB driver | asyncpg | ^0.30 |
| Backend Docker image | `python:3.14` — plný, **NE `-slim`** (asyncpg nemá `cp314` wheel, kompiluje ze zdroje) | — |
| Simulátor | Python + aiomqtt | viz výše |
| Simulátor Docker image | `python:3.14-slim` — `-slim` stačí, jen pure-Python deps | — |
| Frontend framework | React | ^19.2 |
| Frontend build | Vite | ^8.0 |
| Frontend styling | Tailwind CSS (CSS-first config přes `@import "tailwindcss"` a `@theme`) | ^4.3 |
| Frontend jazyk | TypeScript (pragmatická strictness, viz sekce 8 prolog) | ^5.9 |
| Frontend charts | Recharts | ^3.8 |
| Frontend ikony | `@tabler/icons-react` | ^3.44 |
| Frontend router | `react-router-dom` (v6-style API patterns) | ^7 |
| Frontend realtime | Server-Sent Events (SSE) | — |
| MQTT broker | Eclipse Mosquitto | 2.1-alpine |
| Python toolchain | ruff (format + lint) | ^0.15 |
| Frontend toolchain | prettier | ^3.8 |

---

## 3. MQTT

### 3.1 Topic struktura

Versionovaná, hierarchická, oddělené events a commands:

```
Upstream (stanice → broker):
  cpo/v1/stations/{station_id}/events/boot
  cpo/v1/stations/{station_id}/events/heartbeat
  cpo/v1/stations/{station_id}/events/status
  cpo/v1/stations/{station_id}/events/meter

Downstream (broker → stanice):
  cpo/v1/stations/{station_id}/commands/start_charging
  cpo/v1/stations/{station_id}/commands/stop_charging
```

Backend subscribuje `cpo/v1/stations/+/events/+`. Prefix `v1` umožňuje budoucí v2 paralelně bez breaking change. Při budoucím škálování umožňuje shared subscriptions přes `$share/group/cpo/v1/...`.

### 3.2 QoS matice

| Zpráva | QoS | Důvod |
|---|:---:|---|
| Heartbeat | 0 | Frekventní (30 s), ztráta jednoho nešt, offline detekce zachytí trvalý výpadek |
| Status | 1 | Důležitá tranzice, idempotentní |
| Meter | 1 | Billing-relevant, deduplikace v aplikační vrstvě přes `(tx_id, ts)` |
| Commands | 2 | Exactly-once kritické (žádné dvojí účtování) |
| Boot | 1 | Důležitá registrace, retained |
| LWT | 1 | Důležitý offline signál, retained |

### 3.3 Retained messages a LWT

| Topic | Retained | Důvod |
|---|---|---|
| `events/status` | ano | Nový subscriber / restart backendu dostane aktuální stav okamžitě |
| `events/boot` | ano | Registrace stanice persistentní napříč restarty |
| `events/heartbeat` | ne | Časově citlivé, retained by mátlo |
| `events/meter` | ne | Streamovaná data |
| `commands/*` | ne | Imperativní akce, retain by způsobil opakování při reconnectu |

**LWT** nastavený každou stanicí při connectu:
- Topic: `cpo/v1/stations/{id}/events/status`
- Payload: `{"station_id":"ST-001","status":"Offline","reason":"unclean_disconnect"}`
- Retained: true, QoS 1

### 3.4 Persistent session pro ESP32

`clean_session=False` se stabilním `client_id = STATION_ID`:
- Při krátkém WiFi výpadku stanice broker drží QoS 1/2 zprávy a doručí je při reconnectu.
- Příklad: backend pošle `stop_charging` zatímco stanice má 5s výpadek → po reconnectu se stop přesto provede.
- Standard ESP32 pattern, doménově korektní.

### 3.5 Offline detekce

Dvouvrstvá:

1. **LWT** — fast path pro unclean disconnect.
2. **Periodický check** — background task v backendu každých 10 s prochází stanice; pokud `now() - last_heartbeat > 90 s`, status → Offline.

Dvouvrstvost pokrývá situace, kdy LWT nedorazí (síťový partition), i kdy se stanice nikdy nepřipojí.

### 3.6 Heartbeat jitter

Při startu instance: `heartbeat_offset = random.uniform(0, 30)`. Rozprostře heartbeaty při startu 5 stanic najednou, prevence thundering herd. Při budoucí škále (2 000+ stanic) zásadní.

### 3.7 Mosquitto konfigurace

Soubor `mosquitto/config/mosquitto.conf`:

```
listener 1883
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
persistence_file mosquitto.db
autosave_interval 1800
```

- `listener 1883` — TCP default port.
- `allow_anonymous true` — žádná autentizace v MVP.
- `persistence true` + path — retained zprávy přežívají restart brokeru. Kritické pro doménový model: po restartu musí subscriber dostat current status každé stanice z retained topiců, aniž by stanice musela republikovat.
- `autosave_interval 1800` — persistuje retained zprávy na disk každých 30 minut.

V `docker-compose.yml` se config mountuje read-only, data volume je persistent:

```yaml
volumes:
  - ./mosquitto/config:/mosquitto/config:ro
  - mosquitto-data:/mosquitto/data
  - mosquitto-log:/mosquitto/log
```

---

## 4. MQTT message contracts

### 4.1 Konvence

- Timestamps: ISO 8601 UTC (`2026-05-20T08:30:00.000Z`).
- `station_id` v payloadu je redundantní s topicem, ale usnadňuje debug a multi-topic subscribery.

### 4.2 Upstream (stanice → broker)

**Boot** — retained, QoS 1, publikováno při každém connectu:
```json
{
  "station_id": "ST-001",
  "boot_time": "2026-05-20T08:30:00.000Z",
  "firmware_version": "1.0.0",
  "connector_type": "AC",
  "max_power_kw": 22.0,
  "monitoring_agent": "none"
}
```

**Heartbeat** — not retained, QoS 0, každých 30 s + jitter:
```json
{
  "station_id": "ST-001",
  "ts": "2026-05-20T08:30:30.000Z"
}
```

**Status** — retained, QoS 1, jen při tranzici:
```json
{
  "station_id": "ST-001",
  "ts": "2026-05-20T08:30:15.000Z",
  "status": "Charging",
  "transaction_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

Pro `Faulted`:
```json
{
  "station_id": "ST-001",
  "ts": "2026-05-20T08:32:45.000Z",
  "status": "Faulted",
  "error_code": "OverCurrentFailure",
  "transaction_id": "550e8400-..."
}
```

Pro LWT (publikuje broker):
```json
{
  "station_id": "ST-001",
  "status": "Offline",
  "reason": "unclean_disconnect"
}
```

**Meter** — not retained, QoS 1, každých 5 s během Charging:
```json
{
  "station_id": "ST-001",
  "ts": "2026-05-20T08:31:00.000Z",
  "transaction_id": "550e8400-...",
  "power_kw": 21.4,
  "energy_wh": 178
}
```

### 4.3 Downstream (broker → stanice)

**start_charging** — not retained, QoS 2:
```json
{
  "transaction_id": "550e8400-...",
  "issued_at": "2026-05-20T08:30:00.000Z"
}
```

**stop_charging** — not retained, QoS 2:
```json
{
  "issued_at": "2026-05-20T08:45:00.000Z"
}
```

---

## 5. Doménová vrstva

### 5.1 Protocol adapter pattern

```
[MQTT adapter]    ──┐
                    ├──> [SessionService]  ──> DB
[OCPP adapter]*  ──┘
* future work, ne v MVP
```

Struktura kódu v backendu:

- `domain/events.py` — `HeartbeatEvent`, `StatusChangedEvent`, `MeterReadingEvent`, `BootEvent` (Pydantic / dataclasses).
- `domain/session_service.py` — business logika, neví o MQTT.
- `domain/pricing.py` — `PricingStrategy` Protocol, default `FlatRatePricing`.
- `adapters/mqtt_adapter.py` — parsuje MQTT zprávy na doménové eventy, volá SessionService. **Subscriber i publisher** — subscribuje `cpo/v1/stations/+/events/+`, publishuje na `cpo/v1/stations/{id}/commands/*` při REST start/stop call.
- `adapters/rest_api.py` — FastAPI endpointy.
- `adapters/sse.py` — SSE stream.

OCPP adapter (future work) = nový soubor implementující stejný kontrakt, žádná změna domény.

### 5.2 Výpočty

Při uzavření session:

```
total_kwh  = (end_meter_wh - start_meter_wh) / 1000   # zaokrouhleno na 3 desetinná místa
total_cost = total_kwh × PRICE_PER_KWH                # zaokrouhleno na 2 desetinná místa (CZK)
```

`PricingStrategy` Protocol umožňuje budoucí tariff variants (peak/off-peak), default `FlatRatePricing` aplikuje konstantní `PRICE_PER_KWH` z ENV.

Pro aktivní session (zobrazení v UI / API response) se `total_kwh` a `total_cost` **nepočítají** — v `sessions` row jsou `NULL` až do uzavření. Klient si může spočítat průběžnou hodnotu z `(current_meter_wh - start_meter_wh)`, ale tato hodnota není autoritativní.

### 5.3 Session lifecycle při Faulted

Při příjmu status zprávy se `status: "Faulted"`, pokud má stanice aktivní session:

- `sessions.end_time = ts` ze status zprávy
- `sessions.end_meter_wh = last known meter reading` (poslední `MeterReadingEvent` této session; pokud žádný, `= start_meter_wh`)
- `sessions.end_reason = "faulted"`
- `total_kwh` a `total_cost` se dopočítají standardním vzorcem ze sekce 5.2.

Stanice po `FAULT_RECOVERY_SEC` (default 30 s) přejde zpět do `Available`. Pro novou nabíjecí session je nutný nový `start_charging` command s novým `transaction_id`. Žádný auto-resume.

### 5.4 Backend resume on restart

Backend nedrží žádný in-memory critical state. Po restartu:

1. MQTT klient se připojí s `clean_session=True` (subscriber nemá důvod držet queue přes restart).
2. Subscribuje `cpo/v1/stations/+/events/+`.
3. Broker okamžitě doručí **retained** zprávy (boot + last status) za každou stanici — current state je obnoven.
4. Aktivní sessions z DB (řádky s `end_time IS NULL`) zůstávají otevřené. Pokud stanice mezitím fault-la a backend missnul status update, periodic check (sekce 3.5) si toho všimne přes heartbeat timeout a stanici označí jako `Offline` — manuální cleanup aktivních sessions je out-of-scope MVP.

---

## 6. Databáze

### 6.1 Schema

```sql
CREATE TABLE stations (
  id                text PRIMARY KEY,
  connector_type    text NOT NULL DEFAULT 'AC',
  max_power_kw      numeric(6,2) NOT NULL,
  firmware_version  text,
  monitoring_agent  text DEFAULT 'none',
  current_status    text NOT NULL,
  last_heartbeat    timestamptz,
  last_meter_wh     bigint
);

CREATE TABLE sessions (
  id              uuid PRIMARY KEY,
  station_id      text REFERENCES stations(id),
  transaction_id  text UNIQUE NOT NULL,
  start_time      timestamptz NOT NULL,
  end_time        timestamptz,
  start_meter_wh  bigint NOT NULL,
  end_meter_wh    bigint,
  total_kwh       numeric(10,3),
  total_cost      numeric(10,2),
  end_reason      text
);
CREATE INDEX ON sessions (station_id, start_time DESC);
CREATE INDEX ON sessions (station_id) WHERE end_time IS NULL;

CREATE TABLE meter_readings (
  id          bigserial PRIMARY KEY,
  session_id  uuid REFERENCES sessions(id),
  station_id  text NOT NULL,
  ts          timestamptz NOT NULL,
  power_kw    numeric(6,2) NOT NULL,
  energy_wh   bigint NOT NULL
);
CREATE INDEX ON meter_readings (session_id, ts);
CREATE INDEX ON meter_readings (station_id, ts DESC);
```

### 6.2 Poznámky

- `sessions.end_time IS NULL` znamená aktivní session.
- `sessions.end_reason`: `completed`, `faulted`, nebo NULL pro aktivní.
- `stations.current_status`, `stations.last_heartbeat`, `stations.last_meter_wh` jsou cache pro rychlý dashboard read.
- Pro 5 stanic × ~86 k řádků/den je čistý Postgres bez partitioning dostatečný.

### 6.3 Schema initialization

Schema se vytváří přes SQLAlchemy `Base.metadata.create_all()` při backend startup, idempotentně (CREATE TABLE IF NOT EXISTS, žádná chyba při existující tabulce). Pro scope MVP bez Alembic — schema se nemění, migrace nejsou potřeba.

Initial seed: 5 řádků v `stations` z mappingu v sekci 10.2 se vkládá při backend startup přes `INSERT ... ON CONFLICT (id) DO NOTHING`. Hodnoty `current_status` se nastaví na `"Offline"` (real status doplní retained MQTT zprávy z brokeru během prvních sekund).

---

## 7. REST API

Base path: `/api`. JSON. Timestamps ISO 8601 UTC. Error response: `{"error": "msg", "code": "CODE"}`.

**CORS**: backend má povolený origin frontendu (default `http://localhost:8080`) přes `CORSMiddleware`. V MVP žádná autentizace, žádný credentials check. Pro produkční nasazení by se origin omezil na konkrétní doménu a doplnily by se security headers.

### 7.1 `GET /api/stations`

```json
{
  "stations": [
    {
      "station_id": "ST-001",
      "status": "Charging",
      "connector_type": "AC",
      "max_power_kw": 22.0,
      "last_heartbeat": "2026-05-20T08:31:00.000Z",
      "active_session": {
        "transaction_id": "550e8400-...",
        "start_time": "2026-05-20T08:30:00.000Z",
        "energy_wh": 178,
        "power_kw": 21.4
      }
    }
  ]
}
```

`active_session` je `null`, pokud stanice nemá aktivní session.

### 7.2 `GET /api/stations/:id`

```json
{
  "station_id": "ST-001",
  "status": "Charging",
  "connector_type": "AC",
  "max_power_kw": 22.0,
  "firmware_version": "1.0.0",
  "monitoring_agent": "none",
  "last_heartbeat": "...",
  "active_session": { /* same shape */ },
  "recent_meter_readings": [
    {"ts": "...", "power_kw": 21.4, "energy_wh": 178},
    {"ts": "...", "power_kw": 21.2, "energy_wh": 207}
  ]
}
```

`recent_meter_readings`: posledních 60 readings (≈ 5 min při 5 s ticku) pro graf v detail view. Při aktivní session = readings z této session. Při idle = readings z poslední dokončené session. 404 pro neznámé `:id`.

### 7.3 `GET /api/stations/:id/sessions`

Query: `?limit=50&offset=0`.

```json
{
  "sessions": [
    {
      "transaction_id": "550e8400-...",
      "station_id": "ST-001",
      "start_time": "2026-05-20T08:30:00.000Z",
      "end_time": "2026-05-20T08:45:00.000Z",
      "duration_seconds": 900,
      "start_meter_wh": 0,
      "end_meter_wh": 2800,
      "total_kwh": 2.800,
      "total_cost": 15.40,
      "end_reason": "completed"
    }
  ],
  "total": 12
}
```

Probíhající session má `end_time`, `end_meter_wh`, `total_kwh`, `total_cost` jako `null`.

### 7.4 `POST /api/stations/:id/start`

Request:
```json
{ "transaction_id": "550e8400-..." }
```

`transaction_id` je volitelný; pokud chybí, backend generuje UUID. Pokud session s tímto `tx_id` už existuje v DB, vrátí 200 s existující session (idempotent retry).

Response 202:
```json
{
  "transaction_id": "550e8400-...",
  "issued_at": "2026-05-20T08:30:00.000Z",
  "message": "Start command published to station"
}
```

409: `{"error":"...", "code":"STATION_NOT_AVAILABLE", "current_status":"Charging"}`.

### 7.5 `POST /api/stations/:id/stop`

Request: `{}`.

Response 202:
```json
{
  "issued_at": "2026-05-20T08:45:00.000Z",
  "message": "Stop command published to station"
}
```

409: `{"error":"No active session to stop", "code":"NO_ACTIVE_SESSION"}`.

### 7.6 `GET /api/stream/events` (SSE)

Server-Sent Events stream pro real-time frontend updates:

```
event: status_changed
data: {"station_id":"ST-001","status":"Charging","ts":"..."}

event: meter
data: {"station_id":"ST-001","power_kw":21.4,"energy_wh":178,"ts":"..."}

event: session_started
data: {"transaction_id":"...","station_id":"ST-001"}

event: session_ended
data: {"transaction_id":"...","station_id":"ST-001","end_reason":"completed"}
```

Frontend konzumuje přes `EventSource`. Žádná autentizace v MVP.

---

## 8. Frontend

React 19 SPA s Vite buildem, **TypeScript** s pragmatickou strictness, Tailwind v4 pro styling, Recharts pro graf, `@tabler/icons-react` pro status ikony.

**TypeScript scope**: `strict: false` v `tsconfig.json`, jen vybrané flags (`noImplicitAny`, `strictNullChecks`). Type definitions explicitně psané pouze pro klíčové data structures:

- API response shapes z architektury sekce 7 (`Station`, `Session`, `MeterReading`, `StationDetail`, `SessionListResponse`).
- SSE event payloads z architektury 7.6 (`StatusChangedEvent`, `MeterEvent`, `SessionStartedEvent`, `SessionEndedEvent`).
- Konfigurace komponent (props interfaces).

Zbytek typů jde přes inference. Žádné generics nad nezbytné minimum, žádné branded types, žádné conditional types. Pokud typování konkrétního místa trvá víc než 15 minut, použít `any` s `// TODO: tighten type` komentářem.

**Build & serving**: Vite dev server běží v `frontend` containeru na portu 8080 (definováno `FRONTEND_PORT` v ENV). Pro MVP scope žádný production build s nginx — dev server stačí, hot reload je bonus pro development. Backend URL se injectuje při build time přes `VITE_API_URL` (default `http://localhost:3000`), v kódu dostupné jako `import.meta.env.VITE_API_URL`.

### 8.1 Routes

React Router DOM v7 (zachované v6-style API patterns: `<Routes>`, `<Route>`, `useNavigate`, `useParams`), tři routes:

```
/                       — Dashboard (live tabulka 5 stanic)
/stations/:id           — Detail stanice (status, graf, controls)
/stations/:id/sessions  — Historie sessions stanice
```

### 8.2 Color mapping statusů

Konvence shodná s SCADA / EV doménou, použito na badge komponentu napříč Dashboardem i Detail view:

| Status | Tailwind class | Význam |
|---|---|---|
| Available | `bg-green-500` | zelená — ready |
| Preparing | `bg-yellow-500` | žlutá — tranzitní |
| Charging | `bg-blue-500` | modrá — aktivní |
| Finishing | `bg-yellow-500` | žlutá — tranzitní |
| Faulted | `bg-red-500` | červená — error |
| Offline | `bg-gray-400` | šedá — nedostupný |

### 8.3 Dashboard (route `/`)

Tabulka 5 stanic se 4 sloupci pro fleet overview:

| Sloupec | Obsah |
|---|---|
| Station ID | `ST-001` atd. |
| Status | Color-coded badge (viz 8.2) |
| Power | Aktuální výkon v kW při `Charging`, jinak `—` |
| Last heartbeat | Relative time (`5s ago`, `2min ago`) |

Klik na řádek → navigace na `/stations/:id`. Connector type a Max power se v dashboardu nezobrazují — patří do Detail view jako statické atributy stanice.

Data zdroje:
- Initial load: `GET /api/stations` při mount.
- Real-time updates: `GET /api/stream/events` (SSE), filtrace eventů per `station_id`, update lokálního state.

### 8.4 Detail stanice (route `/stations/:id`)

Layout shora dolů:

```
[Header: Station ID, Status badge, Connector type, Max power, Firmware version]
[Controls: Start button (aktivní jen v Available), Stop button (aktivní jen v Charging)]
[Graf: dual-axis LineChart, posledních 5 minut]
[Active session panel (jen když Charging): transaction_id, start_time, energy_wh, duration]
[Link "Zobrazit historii sessions" → /stations/:id/sessions]
```

**Graf detail**: Recharts `LineChart` s dvěma osami. Levá osa `power_kw` (modrá čára), pravá osa `energy_wh` kumulativní pro aktuální (nebo poslední) session (zelená čára). Pokrývá hard requirement "graf výkonu/energie" oběma signály současně. Při aktivní session se data appendují z SSE meter events; při idle stavu graf zobrazuje poslední dokončenou session z `recent_meter_readings`.

Tlačítka jsou podmíněně disabled podle aktuálního statusu — žádný zbytečný request při nevhodném stavu.

Data zdroje:
- Initial load: `GET /api/stations/:id` (status, active session, `recent_meter_readings`).
- Real-time updates: SSE filtrace per `station_id` — append nový meter reading do grafu, update aktuálního statusu, update aktivní session.
- Akce: `POST /api/stations/:id/start`, `POST /api/stations/:id/stop`.

### 8.5 Sessions historie (route `/stations/:id/sessions`)

Tabulka sessions stanice se 6 sloupci:

| Sloupec | Obsah |
|---|---|
| Start time | ISO formátovaný čas |
| End time | ISO čas nebo `—` (pro probíhající session) |
| Duration | Formát `15m 24s` |
| Energy | `2.800 kWh` |
| Cost | `15.40 CZK` |
| End reason | `completed` / `faulted` / `—` |

Default ordering: newest first (odpovídá DB indexu `start_time DESC`).

Paginace: "Load more" tlačítko, načítá dalších 50 sessions přes `?limit=50&offset=N`.

Data zdroj: `GET /api/stations/:id/sessions?limit=50&offset=0`.

### 8.6 State management

Per-view custom React hooks, **žádný global store** (Redux / Zustand / Jotai):

- `useStationsLive()` — pro Dashboard. Drží stav 5 stanic, kombinuje initial fetch s SSE updates.
- `useStationDetail(stationId)` — pro Detail view. Drží detail stanice + meter readings buffer pro graf.
- `useStationSessions(stationId)` — pro Sessions historie. Drží paginated seznam sessions.

Pro 3 obrazovky bez sdíleného stavu mezi nimi je tato granularita správná. Migrace na global store v budoucnu je možná bez breaking changes — hooks interně přejdou z `useState` na store selectors.

### 8.7 SSE konzumace

Custom hook `useSSE(url, eventHandlers)`:

- Otevírá `EventSource` při mount, zavírá při unmount.
- Auto-reconnect při `error` event (browser default behaviour, jen s logováním).
- Per-event-type handler mapping (`status_changed`, `meter`, `session_started`, `session_ended`).

Hook se používá uvnitř `useStationsLive` a `useStationDetail` pro stream `GET /api/stream/events`.

---

## 9. Simulátor

### 9.1 Struktura

Dvouvrstvý:

```
simulator/
  state_machine.py   ← čistá logika (state, transitions, meter accumulation)
  instance.py        ← state machine + aiomqtt klient + tick loop
  config.py          ← StationConfig.from_env()
  __main__.py        ← entry point: load config, create instance, run
```

### 9.2 State machine

| Stav | Význam | Publikuje |
|---|---|---|
| `Available` | Bez session, ready | jen heartbeat |
| `Preparing` | Tranzitní po `start_charging`, 2 s | jen heartbeat |
| `Charging` | Aktivní nabíjení | meter každých 5 s |
| `Finishing` | Tranzitní po `stop_charging`, 2 s | jen heartbeat |
| `Faulted` | Chybový stav, recovery po 30 s | jen heartbeat |
| `Offline` | Existuje jen v retained status topicu (LWT / clean shutdown) | — |

#### Přechody

| Z | Trigger | Do |
|---|---|---|
| `Available` | command `start_charging(tx_id)` | `Preparing` |
| `Preparing` | auto po 2 s | `Charging` |
| `Charging` | command `stop_charging` | `Finishing` |
| `Charging` | probabilistic roll na meter tick | `Faulted` |
| `Finishing` | auto po 2 s | `Available` |
| `Faulted` | auto po `FAULT_RECOVERY_SEC` (default 30 s) | `Available` |
| jakýkoli | SIGTERM | publikuje `Offline` + clean disconnect |
| jakýkoli | unclean disconnect | LWT publikuje `Offline` retained |

#### Edge cases (silent ignore + log warning)

- `start_charging` v Preparing/Charging/Finishing/Faulted → ignore.
- `stop_charging` v Available/Preparing/Finishing/Faulted → ignore.
- `start_charging` se stejným `tx_id` jako aktuální session → ignore (idempotent).
- Neznámý command → ignore.

#### Probabilistic fault

`FAULT_PROBABILITY` aplikuje se per meter tick (každých 5 s ve Charging). Default 0.02. Při faultu náhodný error code z:

```
["InternalError", "OverCurrentFailure", "HighTemperature", "PowerMeterFailure"]
```

#### Meter power profile

Při Charging: `power_kw` = 92–100 % `MAX_POWER_KW` s uniformním šumem.
Akumulace: `energy_wh += power_kw * (5/3600) * 1000`.

### 9.3 Cumulative meter persistence

In-memory only. Při restartu simulátoru se nuluje. Produkční stanice mají persistent meter counter — v MVP simulátoru ne.

### 9.4 Graceful shutdown

SIGTERM → publish `Offline` status retained na `events/status` → clean disconnect (LWT pak nefiruje). Při unclean disconnect LWT publikuje `Offline` místo stanice.

---

## 10. Konfigurace

### 10.1 ENV proměnné (`.env.example`)

```bash
# === MQTT ===
MQTT_HOST=mosquitto
MQTT_PORT=1883
# MQTT_USERNAME=
# MQTT_PASSWORD=

# === Backend ===
BACKEND_PORT=3000
PRICE_PER_KWH=5.50
HEARTBEAT_TIMEOUT_SEC=90

# === Database ===
DB_HOST=db
DB_PORT=5432
DB_NAME=cpo
DB_USER=cpo
DB_PASSWORD=cpo

# === Frontend ===
FRONTEND_PORT=8080
API_URL=http://localhost:3000

# === Simulátor (override per service v docker-compose.yml) ===
# STATION_ID=ST-001
# MAX_POWER_KW=22.0
# FAULT_PROBABILITY=0.02
# FAULT_RECOVERY_SEC=30
# CONNECTOR_TYPE=AC
# FIRMWARE_VERSION=1.0.0
# MONITORING_AGENT=none
```

### 10.2 Konfigurace 5 stanic v `docker-compose.yml`

| Service | STATION_ID | MAX_POWER_KW | FAULT_PROBABILITY | MONITORING_AGENT |
|---|---|---:|---:|---|
| station-1 | ST-001 | 22.0 | 0.02 | none |
| station-2 | ST-002 | 11.0 | 0.02 | rpi |
| station-3 | ST-003 | 22.0 | 0.30 | none (demo fault stanice) |
| station-4 | ST-004 | 22.0 | 0.02 | none |
| station-5 | ST-005 | 7.4 | 0.02 | none |

---

## 11. Implementační pořadí

Bottom-up s rychlou validací po každém kroku:

1. **Mosquitto config + minimalistický `docker-compose.yml`** — validovat broker přes `docker compose up mosquitto`.
2. **Simulátor** — samostatně publikuje zprávy, sledovat přes `mosquitto_sub -h localhost -t '#' -v`.
3. **Backend doménová vrstva + DB schema** — pure logika, testovatelná ve vakuu.
4. **Backend MQTT adapter** — propojení doménové vrstvy s broker streamem, sledovat DB.
5. **Backend REST + SSE** — endpointy nad existující DB, SSE stream.
6. **Frontend** — nad hotovým backend API; nejdřív dashboard, pak detail, pak sessions.
7. **Docker Compose finalizace** — healthchecks, depends_on, volumes.
8. **README + DESIGN.md** — průběžné poznámky, finalizace na konci.
9. **End-to-end test** — `docker compose up` a klikání podle README.
