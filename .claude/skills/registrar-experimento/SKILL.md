---
name: registrar-experimento
description: Añadir una entrada a EXPERIMENTS.md tras una evaluación, destilación, entrenamiento o decisión. Usar cuando termine algo lanzado en la DGX o cuando el usuario pida apuntar un resultado.
---

# Registrar un experimento en EXPERIMENTS.md

El profesor lee EXPERIMENTS.md lo primero al corregir interpretación
(`docs/EXPERIMENTS_plantilla.md`). Una entrada honesta sobre algo que falló vale más que
diez que digan "todo bien".

## Antes de escribir

1. **¿Ya está registrado?** Buscar en EXPERIMENTS.md el mismo experimento. Un log antiguo
   que alguien vuelve a pegar no es un experimento nuevo: comprobar la fecha de los archivos
   (`ls -la --time-style=full-iso`).
2. **Sacar los números de los archivos**, no de memoria ni del resumen del chat: los JSON de
   `reports/`, el `.report.json` de la destilación, `trainer_state.json`, el log.
3. **Fecha = cuándo se ejecutó**, no cuándo se escribe.

## Formato

Separar con `---` y añadir al final (orden cronológico):

```
### AAAA-MM-DD · Fase N · Título corto

**Qué queríamos saber.** La pregunta o la hipótesis.

**Qué hicimos.** Comando exacto (o "el equivalente a …" si no quedó registrado), modelo,
datos, hiperparámetros que cambian respecto a la entrada anterior, duración.

**Qué pasó.** Números en tabla, enlaces a reports/, uno o dos ejemplos concretos.

**Qué concluimos.** Viñetas: qué decidimos y qué hacemos a continuación.
```

## Criterios

- Por familia siempre que haya familias (son seis, más dos fuera de distribución).
- Curvas de RL: medias de 10 pasos o móviles, nunca "primer paso / último paso" (un paso es
  un único problema y es puro ruido).
- Con muestras pequeñas, decirlo; para comparar dos tasas, Fisher exacto bilateral.
- Mirar ejemplos de fallos y decir *por qué* fallan (truncado, formato, regla desconocida).
- Después, commit solo de EXPERIMENTS.md con un mensaje en español.
