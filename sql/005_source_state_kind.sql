-- Tipo atual do endpoint (rss | wpjson | html). Pode mudar quando o healer (L2/L4) repara a fonte.
ALTER TABLE source_state ADD COLUMN IF NOT EXISTS kind TEXT;
