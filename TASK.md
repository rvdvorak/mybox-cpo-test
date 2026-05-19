# Testovací úkol: Mini CPO Platform

Ahoj, díky za zájem o pozici full-stack developera u nás. Posíláme ti zadání úkolu, který nám pomůže ověřit, jak pracuješ s technologiemi, které u nás reálně používáme - **MQTT**, **Docker Compose**, **time-series data** a **realtime UI**.

Zadání simuluje doménu, ve které budeš pracovat (správa flotily EV nabíjecích stanic), ale celé zadání je **greenfield** - žádný náš kód nedostaneš, postavíš mini-systém od nuly.

---

## Co máš postavit

Postav zjednodušenou platformu pro správu flotily **5 EV nabíjecích stanic**. Reálné stanice nemáš, musíš si je simulovat. Komunikace mezi platformou a stanicemi probíhá přes **MQTT broker (Mosquitto)**.

Výsledkem má být **monorepo, které spustíme jediným `docker compose up`** - dostaneme funkční systém:

```
[5× Simulátor stanice]  →  [Mosquitto MQTT]  →  [Backend]  →  [Frontend dashboard]
                                                     ↓
                                                  [DB]
```

---

## Časový rámec a podmínky

- **Cca 14-16 hodin čisté práce** - rozlož si je, jak ti vyhovuje
- **Deadline na odevzdání: 7 dnů od přijetí zadání**
- V `DESIGN.md` na konci uveď, kolik hodin jsi reálně strávil (potřebujeme to pro férové porovnání)
- **AI asistent (Claude Code / Cursor / Copilot) je vítaný a očekávaný** - v pohovoru se budeme ptát, jak jsi ho používal
- **Veřejné knihovny, dokumentace, blogy** - všechno povoleno

---

## Startovací skeleton

Dostaneš odkaz na prázdné GitHub repo se skeletem:

- `docker-compose.yml` - kostra s názvy služeb (`mosquitto`, `db`, `backend`, `frontend`, `station-1` … `station-5`) a sítí. Bez `image`/`build`/`command` - to si doplníš.
- `.env.example` - seznam ENV proměnných
- `README.md` - prázdná kostra (Setup / Run / Test / Architecture)
- `DESIGN.md` - prázdná kostra (Architecture / Tradeoffs / What I'd do differently / Time spent / Use of AI)
- Folder structure: `backend/`, `frontend/`, `simulator/`, `mosquitto/`

**Žádný kód.** Veškerá rozhodnutí (tech stack, schema, MQTT topics, framework) jsou na tobě.

---

## Hard requirements (musí být splněno)

### 1. Simulátor stanice (samostatná Docker služba)

- Při startu se připojí k MQTT brokeru, ohlásí se s `STATION_ID`
- **Publikuje:**
  - **Heartbeat** každých 30 s
  - **Status změny** při přechodu stavu (`Available` → `Preparing` → `Charging` → `Finishing` → `Available`, nebo `Faulted`)
  - **Meter values** během charging session (každých 5 s: aktuální výkon v kW, kumulované Wh)
- **Subscribuje:** příkazy `start_charging` (s `transaction_id`) a `stop_charging`
- **Konfigurovatelné přes ENV:** `STATION_ID`, `MAX_POWER_KW`, `FAULT_PROBABILITY`
- **5 instancí** běží v Docker Compose s různými ID a parametry

### 2. Backend

- Subscribuje MQTT zprávy ze stanic a persistuje data
- **Lifecycle charging session:**
  - **Start:** ulož `start_time`, `station_id`, `start_meter_wh`, `transaction_id`
  - **Updates:** ukládej meter values do time-series formátu
  - **Stop:** ulož `end_time`, `end_meter_wh`, vypočítej `total_kwh` a `total_cost` (cena za kWh konfigurovatelná)
- **Detekce offline:** stanice bez heartbeatu > 90 s → status `Offline`
- **REST API:**
  - `GET /api/stations` - seznam s aktuálním stavem
  - `GET /api/stations/:id` - detail stanice
  - `GET /api/stations/:id/sessions` - historie charging sessions
  - `POST /api/stations/:id/start` - příkaz start nabíjení (publish do MQTT)
  - `POST /api/stations/:id/stop` - příkaz stop nabíjení (publish do MQTT)

### 3. Frontend dashboard

- **Live view:** tabulka 5 stanic s color-coded statusem, real-time updates (bez F5)
- **Detail stanice:** aktuální status, graf výkonu/energie v posledních N minutách, tlačítka Start/Stop
- **Historie sessions:** tabulka se `start/end time`, `energy (kWh)`, `duration`, `cost`

### 4. Docker Compose

- Vše spuštěno jediným `docker compose up`
- **Mosquitto** je předepsán (lightweight, zero-config)
- DB (volba je na tobě), backend, frontend, 5× simulátor
- Healthchecks vítané, ale nejsou hard requirement

### 5. README + DESIGN.md

- **README.md:** instalace, jak spustit, jak otestovat (jak vyzkoušet start/stop session)
- **DESIGN.md (1-2 strany):**
  - Jaké tradeoffs jsi zvážil a proč jsi zvolil daný přístup
  - Co bys udělal jinak, kdybys měl víc času
  - Kde vidíš slabá místa svého řešení
  - Kolik hodin jsi strávil
  - Jak jsi používal AI asistenta - co ti pomohlo, kde ti nebyl k ničemu

---

## Open decisions (volnost - hodnotí se, jak myslíš)

Sám si zvolíš (a obhájíš v `DESIGN.md`):

- **Tech stack backendu** - Node.js/TypeScript preferujeme (máme ho ve stacku), ale Python/Go akceptujeme
- **MQTT topic struktura** - `stations/+/heartbeat` vs `cpo/v1/stations/{id}/events/heartbeat`?
- **QoS levels** - 0/1/2? Pro heartbeat? Pro meter? Pro commands? Proč zrovna takhle?
- **Retained messages** - pro které topics ano, pro které ne?
- **Realtime FE updates** - polling? WebSocket? SSE? MQTT-over-WebSocket přímo do prohlížeče?
- **DB schema** - jedno úložiště, nebo SQL pro metadata + time-series DB pro meter?
- **State management** - in-memory cache, Redis, nebo jen DB?
- **Frontend framework** - React/Vue/Svelte
- **Error handling strategy** - retry? Dead letter queue? Circuit breaker?

---

## Bonus (nice-to-have, není podmínkou)

Pokud zbyde čas a chceš ukázat víc, tyto věci hodnotíme jako **"nad rámec"**. Pozor - dělat bonus na úkor hard requirements je špatná volba.

### Výrazný plus (doménově nejblíž tomu, co reálně děláme)

- **OCPP 1.6 JSON** - místo vlastních MQTT topics implementuj **skutečnou OCPP 1.6 JSON komunikaci** přes WebSocket. Backend hostí OCPP server endpoint (`ws://backend/ocpp/{stationId}`), simulátor stanice je OCPP klient. Implementuj alespoň: `BootNotification`, `Heartbeat`, `StatusNotification`, `StartTransaction`, `MeterValues`, `StopTransaction`. Pokud zvolíš tuhle cestu, MQTT broker můžeš nahradit / vypustit.
- **Pokročilé grafy / dashboard analytics** - kromě basic grafu výkonu v detail view přidej **souhrnný dashboard** s agregacemi: celková energie za den/týden, top 3 stanice po využití, histogram délky session, využitelnost (uptime %) v čase, případně srovnání AC vs DC nabíjení. Hodnotíme volbu vizualizací a smysluplnost metrik.

### Další bonusy

- Unit / integration testy
- Authentication (i základní JWT)
- Per-station rate limiting nebo command queue
- Pricing tarify (peak/off-peak)
- Grafana / Prometheus monitoring
- Healthchecks v `docker-compose.yml`

---

## Jak řešení vyhodnotíme

### Asynchronní část (po odevzdání)

1. **Spuštění u nás** - `docker compose up` musí naběhnout out-of-the-box. Otestujeme všechny REST endpointy a UI flow.
2. **Code review** - projdeme repo, commit historii, code quality.
3. **DESIGN.md** - hodnotíme, jak píšeš o vlastním řešení a zda identifikuješ tradeoffs.

### Synchronní část - 1h pohovor

4. **Live demo + Q&A** - ukážeš nám systém a obhájíš svá rozhodnutí. Typické otázky:
   - "Proč jsi zvolil QoS 1 pro heartbeat a QoS 2 pro meter values?"
   - "Co se stane, když MQTT broker spadne uprostřed session?"
   - "Jak bys to škáloval na 10 000 stanic?"
   - "Kde vidíš největší slabinu svého řešení?"
   - "Co ti AI asistent pomohl udělat rychle a kde ti byl k ničemu?"

### Hodnotící matice

| Dimenze | Váha |
|---|---:|
| Funkčnost end-to-end | 25 % |
| Architektura a rozhodnutí | 25 % |
| MQTT/IoT řemeslnost (QoS, retained, heartbeat, offline) | 20 % |
| Code quality | 15 % |
| Komunikace (README + DESIGN + demo) | 15 % |

### Co EXPLICITNĚ nehodnotíme

- Pixel-perfect frontend (stačí použitelné)
- Plnou OCPP 2.0.1 implementaci nebo OCPP Security Profile 3 (i bonus OCPP 1.6 JSON je zjednodušený - bez TLS, autentizace, persistent storage zpráv)
- Production-grade auth (stačí placeholder nebo nic)
- Plnou test coverage (testy jsou bonus)
- Plnou observability (console logging stačí)

---

## Časté otázky

**Můžu použít knihovnu X?**
Ano, jakoukoli veřejnou. V `DESIGN.md` zmiň, co používáš a proč.

**Co když nestihnu všechno?**
Lepší méně funkcionalit hotových kvalitně než vše napůl. V `DESIGN.md` napiš, co jsi vypustil a proč.

**Co znamená "bonus"?**
Bonus jsou věci nad rámec hard requirements. Pokud uděláš jen hard requirements solidně, je to dostačující. Bonus signalizuje, že chápeš doménu hlouběji nebo máš sílu jít dál. **OCPP 1.6 a pokročilý dashboard jsou pro nás zvlášť cenné** - jdou přímo do oblastí, kde u nás reálně pracujeme. Ale nikdy bonus na úkor hard requirements - vždy nejdřív základ.

**Stačí 3 stanice místo 5?**
Ne, chceme 5 - testujeme i, jak řešíš paralelnost.

**Smím použít serverless / cloud služby?**
Ne, vše musí běžet lokálně v Docker Compose.

**Co když mi něco z requirements není jasné?**
Pošli mail, rádi vyjasníme. Ale interpretace v rámci selského rozumu je v pořádku - i o tom je test.

---

Hodně štěstí! Těšíme se na tvé řešení.
