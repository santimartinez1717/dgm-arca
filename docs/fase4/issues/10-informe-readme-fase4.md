# Fase 4 · Informe (sección de la fase 4), README de portfolio y diagrama

**Responsable:** Kike · **Hito:** H3/H4 · **Depende de:** los resultados de las issues 06 y 07

## Contexto

La entrega final incluye un informe técnico de 10 páginas como máximo, con una página y media
para la fase 4 (`docs/informe_plantilla.md`). También incluye un README de portfolio con un
diagrama de las cuatro fases, la tabla de métricas y el GIF. El contenido de la fase 4 sale
casi entero de lo que mide la issue 06, así que lo escribe quien tiene los números.

## Qué hay que hacer

1. **Sección de la fase 4 del informe**, según la plantilla:
   - el bucle y sus decisiones (timeouts, errores, memoria, confirmaciones, auditor);
   - el banco;
   - éxito, pasos y tokens por cerebro;
   - JSON frente a código;
   - ablaciones (sin auditor, sin playbook, memoria plana);
   - dos trazas buenas y dos malas.
   - Para las decisiones de diseño, partid de `docs/fase4/diseno.md`.
2. **Ejemplo de principio a fin** para la sección 1 del informe: pregunta del usuario, traza y
   respuesta, con una palanca y su cita.
3. **Diagrama de las cuatro fases** en Mermaid o SVG en `docs/`: RLM, tools y RAG dentro del
   agente, con el expediente y el auditor.
4. **README de portfolio**:
   - qué hace y para quién;
   - el GIF (issue 08);
   - el diagrama;
   - la tabla de métricas de las cuatro fases (sacad las cifras de EXPERIMENTS.md, no las
     copiéis de memoria);
   - cómo levantarlo con `docker compose up api`.

## Criterios de aceptación

- Cada cifra del informe y del README coincide con EXPERIMENTS.md o con `reports/fase4/`.
- La sección de la fase 4 cabe en página y media.
- El README se entiende sin haber leído el enunciado.

## Cómo verificar

Que lo revisen Santiago y Bernardo en el PR, y que cada cifra tenga su entrada en EXPERIMENTS.md.
