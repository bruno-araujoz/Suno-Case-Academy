-- Séries do BCB/SGS (Selic, IPCA, câmbio...) para checagem factual futura.
CREATE TABLE IF NOT EXISTS market_series (
    series_code INTEGER NOT NULL,
    series_name TEXT NOT NULL,
    ref_date    DATE NOT NULL,
    value       NUMERIC NOT NULL,
    PRIMARY KEY (series_code, ref_date)
);
