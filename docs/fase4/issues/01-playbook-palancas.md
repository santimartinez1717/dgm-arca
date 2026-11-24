# Fase 4 · Playbook de palancas de inversión con citas verificadas

**Responsable:** Bernardo · **Hito:** H2 · **Depende de:** nada (se puede empezar ya)

## Contexto

El agente de la fase 4 es un analista "listillo": dado un piso y un inversor, busca **palancas
legales** que mejoran la rentabilidad. El cerebro no se las inventa: salen de un catálogo curado,
el playbook. La tool `find_levers` (núcleo) lo filtra por las condiciones del caso y `what_if`
(núcleo) recalcula cada palanca con el motor. Diseño completo en `docs/fase4/diseno.md`, sección
"El playbook de palancas".

## Qué hay que hacer

1. `agent/playbook/levers.yaml` con **al menos 15 palancas**:
   - **Cuantificadas** (con `engine.set`), al menos estas:
     - fecha de firma del contrato frente al RDL 29/2026 (contratos desde el 01/12/2026);
     - reducción del IRPF por inquilino joven en zona tensionada;
     - reducción por rebaja de renta respecto al contrato anterior;
     - reducción por rehabilitación en los dos últimos años;
     - comprar en otra comunidad con menor ITP (comparación de comunidades);
     - valor de referencia frente a precio (el ITP se paga sobre el mayor);
     - obra nueva (IVA + AJD) frente a segunda mano (ITP);
     - amortización: reparto suelo/construcción y valor catastral;
     - gastos deducibles e intereses con arrastre;
     - excepción del 10 % al tope de renta;
     - quedarse por debajo del umbral de gran tenedor;
     - precio máximo de oferta para el objetivo del inversor.
   - **Cualitativas** (`engine: null`): compra a través de sociedad, alquiler de temporada, alquiler
     por habitaciones, subastas del BOE.
   - **`illegal_warning`**, al menos 3, para **detectar y advertir**: precio parcialmente en negro,
     no declarar las rentas, falsear el empadronamiento o la vivienda habitual.
2. El esquema ya existe (`agent/playbook/schema.py`, lo usa `find_levers`), y también 6 palancas
   semilla con sus citas comprobadas en `agent/playbook/levers.yaml`. Completa el catálogo
   siguiendo esas palancas como ejemplo. Si el esquema se queda corto, propón el cambio en la
   issue.
3. Test `tests/test_playbook.py`:
   - el YAML valida;
   - los ids son únicos;
   - las palancas `grey` e `illegal_warning` llevan `risk`;
   - las `explanation` no llevan cifras;
   - **cada `evidence` se localiza en el corpus** con `rag.gold.locate`. Si `rag/corpus` está
     vacío, el test se salta (`pytest.skip`), como hacen los tests de la fase 3.

## Interfaz fija (la usa el núcleo)

```yaml
- id: snake_case_unique
  level: legal | grey | illegal_warning
  title: Título corto en español
  applies_when:                    # AND de condiciones; lista vacía = siempre
    - {field: property.stressed_zone, op: eq, value: true}
    - {field: profile.properties_owned, op: lt, value: 10}
  engine:                          # null si es cualitativa
    set: {property.contract_date: "2026-11-30"}   # campos de Property / InvestorProfile
  evidence:
    source: boe/rdl-29-2026.md     # ruta dentro de rag/corpus
    section: Artículo 1
    quote: "cita literal"
  risk: null                       # texto obligatorio si level != legal
  explanation: Texto para el usuario, sin cifras.
```

- `op` ∈ `eq, ne, lt, le, gt, ge, in, is_null, not_null`.
- Los campos son los de `InvestorProfile` y `Property` (`docs/fase4/diseno.md`, sección "El
  expediente"). Si te falta un campo, pídelo en la issue: no lo inventes por tu cuenta.
- `engine.set` también admite valores especiales que interpreta `what_if`: `"$cheapest_itp_region"`
  y `"$max_offer_price"`. Si necesitas otro, documéntalo en la palanca y avisa.

## Criterios de aceptación

- 15 palancas o más, con al menos 3 de cada nivel no legal (`grey`, `illegal_warning`).
- `uv run pytest tests/test_playbook.py` en verde, con corpus y sin él.
- Ninguna palanca cita un documento que no esté en `rag/corpus/`. Si una palanca necesita una fuente
  que no tenemos (bonificaciones autonómicas del ITP), apúntala en la issue 04.

## Cómo verificar

```bash
uv run python -c "from agent.playbook.schema import load_levers; print(len(load_levers()))"
uv run pytest -q tests/test_playbook.py
uv run ruff check && uv run ruff format
```
