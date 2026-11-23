# mala: lever-01 (full/base)

- Categoría: `lever` · correcta: **False** · pasos: 5 · tokens: 24419
- Tools usadas: analyze_property, find_levers, record_investor, record_property

## Tarea

Compro un piso de segunda mano de 70 m² en Madrid por 200.000 €, al contado. El inquilino anterior pagaba 1.000 € al mes y al nuevo le voy a cobrar 1.030 €. Pensaba firmar el 15/12/2026. Valor catastral 90.000 € (40 % suelo), IBI 400 €, comunidad 60 € al mes y seguro 180 €. ¿Hay alguna forma legal de pagar menos IRPF por el alquiler?

## Paso 1

**Pensamiento:** —

**Acción:** `record_property` `{"property_id": "P1", "municipality": "Madrid", "price": 200000, "monthly_rent": 1030, "area_m2": 70, "reference_value": 90000, "land_share_pct": 40, "ibi": 400, "community_monthly": 60, "insurance": 180, "stressed_zone": null, "contract_date": "2026-12-15"}`

**Observación:**

```
{"property_id": "P1", "saved": ["area_m2", "community_monthly", "contract_date", "ibi", "insurance", "land_share_pct", "monthly_rent", "municipality", "price", "reference_value"], "next": "analyze_property"}
```

## Paso 2

**Pensamiento:** —

**Acción:** `record_investor` `{"region": "Comunidad de Madrid", "properties_owned": 0, "properties_owned_stressed": 0, "financing": null, "down_payment_pct": 100, "interest_rate_pct": null, "loan_years": null, "marginal_tax_rate_pct": 25, "target_net_yield_pct": 5}`

**Observación:**

```
{"saved": ["down_payment_pct", "marginal_tax_rate_pct", "properties_owned", "properties_owned_stressed", "region", "target_net_yield_pct"]}
```

## Paso 3

**Pensamiento:** The property details have been recorded, and the investor's information is saved. Now, I need to analyze the property to determine if there are any legal ways to pay less IRPF on the rent.

**Acción:** `analyze_property` `{"property_id": "P1"}`

**Observación:**

```
{"property_id": "P1", "price": 200000.0, "itp_rate_pct": 6.0, "transfer_tax": 12000.0, "total_investment": 212000.0, "asking_rent": 1030.0, "effective_rent": 1030.0, "collected_rent": 12360.0, "operating_costs": 1300.0, "net_income": 11060.0, "gross_yield_pct": 5.83, "net_yield_pct": 5.22, "region": "madrid", "stressed_zone": false, "large_holder": false, "rules": {"stressed_zone": "municipio sin declaración vigente"}, "missing": ["cadastral_value and land_share_pct (IBI receipt) for the IRPF"]}
```

## Paso 4

**Pensamiento:** The analysis of the property P1 shows that the IRPF calculation is missing the cadastral value and land share percentage, which are necessary for the IRPF. These values are not provided by the user, so I need to check if they can be obtained or if there are any legal ways to adjust the IRPF calculation.

**Acción:** `find_levers` `{"property_id": "P1"}`

**Observación:**

```
{"property_id": "P1", "applicable": [{"id": "rehabilitation_before_contract", "level": "legal", "title": "Rehabilitar antes de firmar el contrato", "quantified": true, "source": "boe/lirpf.md · Artículo 23"}, {"id": "offer_at_max_price", "level": "legal", "title": "Ofrecer como máximo el precio que da la rentabilidad objetivo", "quantified": true, "source": "boe/trlitpajd.md · Artículo 10"}, {"id": "short_term_rental", "level": "grey", "title": "Alquiler de temporada o turístico en lugar de vivienda habitual", "quantified": false, "source": "boe/rdl-29-2026.md · Preámbulo", "risk": "Si en realidad es la vivienda habitual del inquilino, el contrato se rige por la LAU y sus topes de renta; además, desde el 1 de diciembre de 2026 ciertos alquileres cortos pagan IVA y no tienen la reducción del IRPF."}], "next": "call what_if with the quantified ids to see what each one is worth"}
```

## Paso 5

**Pensamiento:** [sin final_answer: el texto se toma como respuesta] The find_levers function has identified potential legal levers for the property P1, including rehabilitation before the contract, offering at the target price, and short-term rentals. These levers are either quantified or grey, with some carrying risks. I need to call what_if with the quantified levers to assess their impact on the IRPF and overall investment.

**Observación:**

```
Audit passed.
```

## Respuesta final

The find_levers function has identified potential legal levers for the property P1, including rehabilitation before the contract, offering at the target price, and short-term rentals. These levers are either quantified or grey, with some carrying risks. I need to call what_if with the quantified levers to assess their impact on the IRPF and overall investment.

Análisis orientativo hecho con datos sintéticos y las reglas vigentes que conoce el motor; no es asesoramiento. Consulta a un asesor fiscal antes de decidir.
