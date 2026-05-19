# Design dokument

> 1-2 strany. Tady ukážeš, jak myslíš. Nebudeme tě hodnotit za to, že jsi něco neudělal "ideálně" - hodnotíme, jak jsi o tom přemýšlel.

## Architektura

> Jak jsi rozdělil systém na služby a proč? ASCII diagram / odkaz na obrázek vítaný.
> Jaký tech stack jsi zvolil (backend / frontend / DB) a proč?

## Klíčové tradeoffs

> Pro každé z těchto rozhodnutí napiš: **co jsem zvolil**, **proč**, a **co jsem zvažoval místo toho**:

### MQTT topic struktura
>

### QoS levels (pro heartbeat / status / meter / commands)
>

### Retained messages
>

### Realtime FE updates (polling / WebSocket / SSE / MQTT-WS)
>

### DB schema (jedno úložiště vs. SQL + time-series)
>

### State management (in-memory / Redis / jen DB)
>

### Error handling (retry / DLQ / circuit breaker)
>

## Co bych udělal jinak s víc časem

> 3-5 bodů, co je dle tebe v současné podobě slabé místo a jak bys to dořešil.

## Slabá místa současného řešení

> Buď k sobě kritický. Co se rozbije pod zátěží? Co se rozbije, když MQTT broker spadne? Co když databáze přijde o čas (NTP issue)? Co když se stanice připojí dvakrát se stejným ID?

## Čas

> Kolik hodin čisté práce jsi strávil? Rozdělené hrubě na: discovery/research, BE, FE, simulátor, Docker setup, dokumentace.

## Spolupráce s AI asistentem

> Jaký AI asistent jsi použil? Co ti pomohl udělat rychle? Kde ti byl k ničemu / co jsi musel řešit sám?
> Případně jakou techniku jsi použil (Claude Code agentic, Cursor inline, Copilot autocomplete)?
