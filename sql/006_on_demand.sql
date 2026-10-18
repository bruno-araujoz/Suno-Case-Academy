-- Coleta sob demanda: uma linha por fonte com a última checagem e a pausa do healer.
CREATE TABLE IF NOT EXISTS source_checks (
    source      TEXT PRIMARY KEY,
    checked_at  TIMESTAMPTZ,            -- última vez que a fonte foi consultada (TTL conta daqui)
    heal_after  TIMESTAMPTZ             -- healer não tenta reparar antes disso (cooldown)
);
