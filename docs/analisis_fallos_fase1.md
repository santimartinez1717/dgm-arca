# Fase 1 · Análisis de cinco fallos del modelo final

Modelo: Qwen3-1.7B + LoRA tras SFT y GRPO (`rlm/weights/final_rlm_lora`), evaluado en los 300
problemas de test con 2.048 tokens y decodificación greedy (`reports/eval_grpo_17b_2048.json`,
pass@1 = 38,3 %). Hay 185 fallos: 24 respuestas cortadas y 161 que terminan con una cifra
equivocada. Elegimos cinco que representan un patrón distinto cada uno y contamos cuántas
veces se repite ese patrón en el test.

| # | Familia | Esperado | Respuesta | Patrón | Cuántos |
|---|---|---|---|---|---|
| 1 | `acquisition_cost` | 191.450,50 € | 176.014,50 € | Obra nueva sin IVA | 10 de 11 problemas de obra nueva (0 aciertos) |
| 2 | `cash_on_cash` | 5,36 % | 13,17 % | No resta la cuota de la hipoteca | 17 de 43 fallos de la familia |
| 3 | `irpf_rental` | 5.909,32 € | 4.827,90 € | No calcula la amortización | 34 de 42 fallos de la familia |
| 4 | `max_price` | 100.285,71 € | 100.000,00 € | Ecuación bien, división mal | 24 de 27 fallos a menos del 1 % |
| 5 | `legal_rent` | 9.480,00 € | 762,55 € | Bucle de repetición y regla mal aplicada | 41 de 300 salidas repiten una frase 3 o más veces |

## 1. Obra nueva sin IVA (`acquisition_cost`)

> Piso de obra nueva por 171.500 €, valor de referencia 138.400 €, notaría 1.600 €, AJD 0,7 %.

El alumno suma precio + "ITP (Impuesto sobre el Valor Añadido) del 1 %" + AJD + notaría =
176.014,50 €. Lo correcto es precio + **IVA del 10 %** (17.150 €) + AJD sobre el mayor de precio
y referencia (1.200,50 €) + notaría = 191.450,50 €. Confunde el nombre de los impuestos y se
inventa un tipo del 1 %.

**Por qué.** Es el mismo error que cometía el profesor sin la hoja de reglas: el IVA no
aparece en el enunciado porque se da por sabido. En el SFT el alumno vio solo 15 trazas de obra
nueva (el 11 % de la familia), todas con IVA, y no le bastaron. GRPO no puede corregirlo: con 0
aciertos en el grupo de 8 respuestas, la ventaja de todas es 0. El 74-78 % de
`acquisition_cost` sale entero de la vivienda usada; en obra nueva el modelo saca un 0 % (0 de 11).

## 2. Cash-on-cash sin la cuota de la hipoteca (`cash_on_cash`)

> Inversión 449.000 €, préstamo 249.000 € a 20 años al 2,35 %, ingreso neto operativo
> 26.330 €. Flujo de caja sobre capital propio.

El alumno calcula los fondos propios bien (200.000 €) y divide el ingreso entero entre ellos:
13,17 %. Lo dice explícitamente: "the fixed interest rate is 2.35%, but since the net income is
already provided, that's not needed". Lo correcto es restar 12 cuotas de 1.301,34 € (15.616 €):
10.713,92 / 200.000 = 5,36 %.

**Por qué.** Calcular la cuota a mano exige (1 + i)^−240, que es largo: con 2.048 tokens las
trazas del profesor se cortaban el 65 % de las veces y solo hubo 56 trazas de esta familia para
el SFT, las más largas del conjunto (mediana de 1.862 tokens). El alumno aprendió el atajo:
saltarse la cuota. En 17 de los 43 fallos no la calcula. En otros la calcula, pero con
aproximaciones (e^x en lugar de la potencia) o divide entre la inversión total en lugar de los
fondos propios, como en el problema de 105.000 € a 15 años (0,64 % frente a 1,36 %).

## 3. Rendimiento del IRPF sin amortización (`irpf_rental`)

> Ingresos 18.300 €, inquilino de 37 años, zona tensionada, primer alquiler, coste de
> adquisición 293.000 €, catastral 102.000 € (suelo 52.400 €), IBI 355 €, comunidad 1.630 €,
> seguro 222 €.

El alumno resta IBI, comunidad y seguro (16.093 €) y aplica una reducción del 70 % "porque es el
primer alquiler": 4.827,90 €. Falta la **amortización**, 3 % × 293.000 × (1 − 52.400 / 102.000)
= 4.274,35 €, y la reducción del 70 % exige un inquilino de 18 a 35 años: con 37 corresponde el
50 %. Lo correcto: 11.818,65 × 0,5 = 5.909,32 €.

**Por qué.** La amortización es el paso más largo y menos evidente (el coste de adquisición
aparece en el enunciado, pero no dice para qué sirve). En 34 de los 42 fallos de la familia el
alumno no la calcula. Además encadena condiciones de la reducción que no se cumplen o se inventa
rangos ("18-35 or 36-40"). Es la familia con más pasos encadenados, y un error en cualquiera
arrastra el resultado.

## 4. Ecuación correcta, división equivocada (`max_price`)

> Ingreso neto 6.600 €, objetivo del 6 %, ITP del 5 %, otros gastos 4.700 €.

El alumno plantea bien 6.600 / (1,05·P + 4.700) = 0,06 y llega a 105.300 = 1,05·P, pero divide
mal: P = 100.000 €. Lo correcto es 105.300 / 1,05 = 100.285,71 €. Después "comprueba" el
resultado y redondea la comprobación a "≈ 0,06" sin notar la diferencia.

**Por qué.** No es un error de razonamiento sino de cálculo: en 24 de los 27 fallos de la
familia la respuesta está a menos de un 1 % de la correcta, pero la tolerancia es del 0,05 %. Es
también donde GRPO empeoró al SFT (56 % → 42 %, 10 de los 22 problemas que el SFT acertaba y
GRPO no). Una explicación posible, que no hemos medido: al premiar respuestas más cortas, el
modelo deja de hacer las divisiones paso a paso.

## 5. Bucle de repetición y regla mal aplicada (`legal_rent`)

> Zona tensionada, contrato anterior hace dos años con renta actualizada de 755 €/mes, obras de
> eficiencia energética después, 44 m² a 17,5 €/m², mercado 790 €/mes. Renta máxima del
> **primer año**.

El alumno aplica la excepción de las obras como un 1 % (755 + 7,55 = 762,55) en lugar de un 10 %
(830,50 €/mes, por encima del mercado, así que manda el mercado: 790 €/mes) y da la renta
**mensual** cuando se pide la anual (9.480 €). El razonamiento entra en bucle: repite una y otra vez
"the index-based rent is 770, but the owner had a contrato habitual which caps it to 762.55.
Therefore, the maximum rent is 762.55" hasta que cierra.

**Por qué.** Cuando el modelo duda entre dos topes, en lugar de resolver la duda la repite. 41
de las 300 salidas repiten alguna frase tres o más veces. Es un síntoma conocido de la
decodificación greedy en modelos pequeños, y GRPO no lo penaliza mientras la respuesta llegue a
cerrar.

## Un problema transversal: el alumno cita una hoja que no ha visto

En 80 de las 300 salidas el alumno escribe "From the background knowledge…". La hoja de reglas
del profesor empezaba por "The following is background knowledge…", y 143 de las 703 trazas
verificadas del SFT la citan con esa expresión. El filtro de citas de `rlm/distill.py` buscaba
"rules provided" o "the notes", pero no esta frase, así que las trazas pasaron y el alumno
aprendió a referirse a un conocimiento que no tiene delante. No cambia la cifra final por sí
solo, pero es una fuga. Ya hemos añadido la expresión al filtro para futuras destilaciones.

## Qué sacamos

- **Los fallos son de conocimiento del dominio y de cálculo, no de formato**: el 92 % de las
  respuestas tiene formato válido y solo un 8 % se corta.
- **Lo que el SFT no enseña, GRPO no lo arregla.** Obra nueva, la cuota de la hipoteca y la
  amortización tienen muy pocos aciertos en el grupo de 8, así que no hay señal de la que
  aprender.
- **Una calculadora resolvería el fallo 4 y buena parte del 2 y el 3**: en ellos el
  planteamiento es correcto y falla la aritmética. Es el caso de uso de la herramienta de cálculo
  de la fase 2.
