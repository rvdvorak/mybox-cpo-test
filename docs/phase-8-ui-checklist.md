# Fáze 8 — manuální UI proklik checklist

Implementační/CI session nemá prohlížeč, takže `phase-8-e2e.sh` ověřuje backend,
MQTT, DB a SSE, ale **ne chování UI v prohlížeči** (klik, živé překreslení bez
F5, graf, navigace). Tenhle checklist projde člověk ručně. Je zároveň polotovar
README sekce „Test" pro Fázi 9 — kroky jsou psané tak, aby šly přenést skoro
beze změny.

## Předpoklady

1. `docker compose up -d --build` — celý stack běží (viz README Setup/Run).
2. Počkat, až jsou služby `healthy`: `docker compose ps` (sloupec STATUS).
3. Frontend: <http://localhost:8080> · Backend API: <http://localhost:3000/api>.
4. Otevřít frontend v prohlížeči. Doporučeno mít vedle otevřenou konzoli
   prohlížeče (Network → EventStream), aby byl vidět SSE stream.

Status badge — barevné kódování: `Available` zelená, `Charging` modrá,
`Preparing`/`Finishing` přechodové, `Faulted` červená, `Offline` šedá.

---

## 1. Dashboard (`/`)

- [ ] Na `/` se načte tabulka s **5 stanicemi** (ST-001 až ST-005).
- [ ] Každý řádek má sloupce: **Station ID**, **Status** (barevný badge),
      **Power** (kW, nebo `—` když nenabíjí), **Last heartbeat** (relativní čas).
- [ ] Po startu jsou stanice ve stavu `Available` (po chvíli, jak backend
      zpracuje retained status z brokeru — po startu mohou krátce být `Offline`).
- [ ] Hodnota „Last heartbeat" se sama průběžně aktualizuje (~30 s) **bez F5**.

## 2. Start session přes UI (živý update bez F5)

- [ ] Klik na řádek stanice `ST-001` → otevře se detail `/stations/ST-001`.
- [ ] Detail ukazuje hlavičku (ID, status, connector, max kW, firmware —
      dle architektury §8.4) a tlačítko **Start**.
- [ ] Klik na **Start**. **Bez obnovení stránky** sledovat přechod statusu:
      `Available` → `Preparing` (~2 s) → `Charging`.
- [ ] Po přechodu do `Charging` se objeví panel **aktivní session**
      (transaction ID, čas startu, energie, výkon).
- [ ] Přepnout na druhou záložku/okno s Dashboardem (`/`) — řádek `ST-001`
      tam ukazuje `Charging` taky **bez F5** (SSE doručuje update na všechny
      otevřené obrazovky).

## 3. Live graf (detail stanice)

- [ ] Na detailu `Charging` stanice je graf (Recharts, dvě osy: výkon kW /
      energie Wh).
- [ ] Každých ~5 s přibude do grafu nový bod (meter reading) — **bez F5**.
- [ ] Po ~30 s je v grafu vidět průběh několika měření.

## 4. Stop session přes UI

- [ ] Na detailu nabíjející `ST-001` klik na **Stop**.
- [ ] **Bez F5** status přejde `Charging` → `Finishing` → `Available`.
- [ ] Panel aktivní session zmizí.
- [ ] Klik na odkaz na historii session (`/stations/ST-001/sessions`) —
      právě ukončená session je v tabulce: čas startu, čas konce, délka,
      energie (kWh), cena (CZK), `end_reason = completed`.

## 5. Navigace mezi 3 obrazovkami

- [ ] `/` (Dashboard) → klik na stanici → `/stations/:id` (detail).
- [ ] `/stations/:id` → odkaz na historii → `/stations/:id/sessions`.
- [ ] Tlačítko zpět v prohlížeči funguje na všech přechodech.
- [ ] Přímé zadání URL `/stations/ST-002` do adresního řádku načte detail
      (SPA routing přežije reload).
- [ ] Sessions stránka s víc než stránkou záznamů ukazuje stránkování.

## 6. Offline detekce

- [ ] V terminálu: `docker compose kill station-4`.
- [ ] V UI (Dashboard nebo detail `ST-004`) status `ST-004` přejde na
      `Offline` — **prakticky okamžitě** (LWT / graceful shutdown), bez F5.
      Nečekej „90 s" — 90 s heartbeat-timeout je jen záloha pro nedoručený LWT.
- [ ] `docker compose start station-4` → stanice se po chvíli vrátí na
      `Available`.

## 7. Fault scenario

- [ ] `ST-003` má `FAULT_PROBABILITY=0.30` (30 % na každý 5s meter tick).
- [ ] Otevřít detail `ST-003`, klik **Start**, sledovat nabíjení.
- [ ] Se zhruba 30% šancí na každý tick stanice přejde do `Faulted` (červený
      badge) — **bez F5**. Session se uzavře s `end_reason = faulted` (viz
      historie session). Pozn.: `error_code` faultu UI nezobrazuje — není
      v API kontraktu detailu (architektura §7.2), je jen v MQTT/DB vrstvě.
- [ ] Pokud fault během session nepadne, klik **Stop** a **Start** znovu a
      opakovat — pravděpodobnostní jev, do pár pokusů fault padne.
- [ ] Faulted stanice se po ~30 s (`FAULT_RECOVERY_SEC`) sama vrátí na
      `Available`.
- [ ] Ostatní stanice mají `FAULT_PROBABILITY=0.02` — fault je tam vzácný.
