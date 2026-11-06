# Registro de experimentos — edge-medicine (NAVAJO como pasarela de privacidad para JupyterHealth)

Datos: Nemotron-PII (CC BY 4.0) dominios sanitarios; train Healthcare+Pharmaceuticals (6750 docs), test Health+Healthcare Providers (7058 docs);
cada uid aparece en dos variantes (us/intl) → clave `uid_locale`, partición por uid base (las dos variantes juntas, sin fuga).
Gretel pii-masking-en-v1 (Apache-2.0) test, dominios healthcare/healthcare-administration/pharmaceuticals-biotechnology (403 docs) como conjunto fuera de distribución.
Métrica primaria: recall de PHI por carácter (identificadores HIPAA Safe Harbor), precisión, F2; secundarias: recall de entidad completa, secretos, valores clínicos conservados, latencia p50/p95 y RSS con 2 hilos.

| id | fecha (UTC) | hipótesis | config | datos | resultado | decisión |
|---|---|---|---|---|---|---|
| E001 | 2026-10-29 05:10 | línea base: NAVAJO v1 tal cual (regex, sin spaCy) | navajo_egp v1 | train 1500 docs | char recall 0,711, precisión 0,374, F2 0,603; 1 caída (`matched.index(" ")` con nombres separados por salto de línea) | v1 insuficiente; diseñar v2 |
| E002 | 2026-10-29 05:30 | capa clínica (clave-valor, formas de ID, fechas, léxico de nombres de train) sube recall sin perder precisión | navajo_v2 iter. 1, léxico de train particiones 0-1 | train partición 2 (2308 docs) | recall 0,933, precisión 0,919, F2 0,930, clínicos conservados 0,928 | iterar: rangos clínicos («70-100») enmascarados |
| E003 | 2026-10-29 05:45 | excluir rangos, fechas con separador coherente, teléfonos internacionales, condados, ciudades tras dirección, alias | navajo_v2 iter. 2 | train partición 2 | recall 0,948, precisión 0,926, F2 0,943, clínicos 0,974; sin léxico F2 0,894 | **v2 congelado** |
| E004 | 2026-10-29 06:20 | prueba de fontanería (no de selección) | v1, v2, v2-sin-léxico | 300 docs de test | v2 F2 0,909 vs v1 0,550 | sin cambios posteriores a v2; el test completo se evalúa una vez en server-ia |
| E005 | 2026-10-29 06:30 | validación del entorno en server-ia | job cb570df1361643ee (quick, 200 docs) | Nemotron y Gretel, 200 docs cada uno | v2 F2 0,910 y 0,879; hybrid 0,933 y 0,960 | piloto exploratorio; sin reselección |
| E006 | 2026-10-29 06:55 | benchmark completo | job 4ed488c393f24a72, terminado con éxito, recogido el 2026-11-06 | Nemotron salud 7058 + Gretel salud 403 | v2 F2 0,918 ± 0,002 y 0,879 ± 0,021; Presidio 0,838 y 0,800; GLiNER 0,752 y 0,941; v2 + GLiNER 0,942 y 0,957 | sin cambios en v2; verificado el 2026-11-06: tramos de v2 reproducidos en 7461 de 7461 documentos y 2592 valores repuntuados con diferencia 0 |
