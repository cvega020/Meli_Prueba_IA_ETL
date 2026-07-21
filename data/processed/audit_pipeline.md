# Auditoria de ejecucion del pipeline

## Metadatos

- Inicio (UTC): 2026-07-21T00:05:45.272652+00:00
- Fin (UTC): 2026-07-21T00:05:48.837119+00:00
- Duracion total (s): 3.564

## Parametros

- docs_root: docs_raw
- processed_dir: data\processed
- lsh_threshold: 0.9
- lsh_num_perm: 128
- lsh_shingle_size: 3
- qa_model: google/flan-t5-small
- qa_chunk_size: 1800
- questions_per_chunk: 2
- qa_fallback_only: True

## Etapas

- Ingesta y limpieza: 0.112s | documentos: 88
- Deduplicacion: 3.442s | documentos unicos: 59
- Export corpus: 0.002s
- Generacion Q&A + export: 0.007s | filas Q&A: 274

## Salidas

- Corpus: data/processed/corpus.jsonl
- Q&A: data/processed/qa_dataset.jsonl

## Deduplicacion

- Documentos descartados por similitud: 29

| discarded_id | discarded_file | kept_id |
|---|---|---|
| 2a1490f3efce9f48f0a2af837381dd2c | 2p-revenue-optimizer-api/latest/guide/pages/table_data_dictionary/rule_row.md | 5272a5d0ee1e5c4e0abacb1787db35ba |
| c26fa31bd20e0cf371b639979cdc13a1 | 2p-revenue-optimizer-api/latest/guide/README.md | c26fa31bd20e0cf371b639979cdc13a1 |
| 36140859e1e1de022e6757fec5d1e6a8 | catalog-portfolio-api/latest/guide/_sidebar.md | 36140859e1e1de022e6757fec5d1e6a8 |
| 61bfb6e4d18f27e9b0b2456b307c7723 | catalog-portfolio-api/latest/guide/api-reference/brands.md | 61bfb6e4d18f27e9b0b2456b307c7723 |
| 1a5b0b127cb6212911017ad917c30b52 | catalog-portfolio-api/latest/guide/api-reference/README.md | 1a5b0b127cb6212911017ad917c30b52 |
| 91486962a9b25d40453e57c449841963 | catalog-portfolio-api/latest/guide/architecture/README.md | 91486962a9b25d40453e57c449841963 |
| 5a2f5a5fbe03c51e280fbc04e480ea8e | catalog-portfolio-api/latest/guide/brand-management/README.md | 5a2f5a5fbe03c51e280fbc04e480ea8e |
| 8b21c6a3f6a41f5a33879b38c4b7fae3 | catalog-portfolio-api/latest/guide/README.md | 8b21c6a3f6a41f5a33879b38c4b7fae3 |
| 384a6cff7243a0024397d40c1dbbe585 | catalog-portfolio-api/latest/guide/setup/local-development.md | 384a6cff7243a0024397d40c1dbbe585 |
| a4e3a78d36ed886c83ccc6b027260629 | catalog-portfolio-api/latest/guide/setup/README.md | a4e3a78d36ed886c83ccc6b027260629 |
| c9c70e4a899f88ef6e90e3bfa10e3d56 | catalog-portfolio-api/latest/guide/troubleshooting/README.md | c9c70e4a899f88ef6e90e3bfa10e3d56 |
| 649a111fa3ed6177fd0d11dd701d50f3 | payment-promise-gateway/latest/guide/README.md | 649a111fa3ed6177fd0d11dd701d50f3 |
| 9c947fcbdc71c3b6e3e5d32e550536d3 | vendor-stockkeeper-api/0.0.3-paused-seller/guide/_sidebar.md | 9c947fcbdc71c3b6e3e5d32e550536d3 |
| e322155963528af9c0f2bbf61ce65877 | vendor-stockkeeper-api/0.0.3-paused-seller/guide/alerts.md | 5af43b87c21a03575f9a3a31feec1d5a |
| d7156eea367882558cb94875398efea8 | vendor-stockkeeper-api/0.0.3-paused-seller/guide/database.md | d7156eea367882558cb94875398efea8 |
| 7e48805ea05204a6e4923652cec7d874 | vendor-stockkeeper-api/0.0.3-paused-seller/guide/introduction.md | 7e48805ea05204a6e4923652cec7d874 |
| dad636720a4a5301964fe5ef444277bc | vendor-stockkeeper-api/0.0.6-ep-restock-man/guide/_coverpage.md | dad636720a4a5301964fe5ef444277bc |
| 9c947fcbdc71c3b6e3e5d32e550536d3 | vendor-stockkeeper-api/0.0.6-ep-restock-man/guide/_sidebar.md | 9c947fcbdc71c3b6e3e5d32e550536d3 |
| 9f10e5b4b3fb3806bccc988bec4bf14c | vendor-stockkeeper-api/0.0.6-ep-restock-man/guide/api.md | 9f10e5b4b3fb3806bccc988bec4bf14c |
| d7156eea367882558cb94875398efea8 | vendor-stockkeeper-api/0.0.6-ep-restock-man/guide/database.md | d7156eea367882558cb94875398efea8 |
| 5a4cd2dbee9da08bf58b794bfe518d85 | vendor-stockkeeper-api/0.0.6-ep-restock-man/guide/important.md | 5a4cd2dbee9da08bf58b794bfe518d85 |
| 7e48805ea05204a6e4923652cec7d874 | vendor-stockkeeper-api/0.0.6-ep-restock-man/guide/introduction.md | 7e48805ea05204a6e4923652cec7d874 |
| dad636720a4a5301964fe5ef444277bc | vendor-stockkeeper-api/latest/guide/_coverpage.md | dad636720a4a5301964fe5ef444277bc |
| 9c947fcbdc71c3b6e3e5d32e550536d3 | vendor-stockkeeper-api/latest/guide/_sidebar.md | 9c947fcbdc71c3b6e3e5d32e550536d3 |
| e322155963528af9c0f2bbf61ce65877 | vendor-stockkeeper-api/latest/guide/alerts.md | 5af43b87c21a03575f9a3a31feec1d5a |
| 9f10e5b4b3fb3806bccc988bec4bf14c | vendor-stockkeeper-api/latest/guide/api.md | 9f10e5b4b3fb3806bccc988bec4bf14c |
| d7156eea367882558cb94875398efea8 | vendor-stockkeeper-api/latest/guide/database.md | d7156eea367882558cb94875398efea8 |
| 5a4cd2dbee9da08bf58b794bfe518d85 | vendor-stockkeeper-api/latest/guide/important.md | 5a4cd2dbee9da08bf58b794bfe518d85 |
| 7e48805ea05204a6e4923652cec7d874 | vendor-stockkeeper-api/latest/guide/introduction.md | 7e48805ea05204a6e4923652cec7d874 |
