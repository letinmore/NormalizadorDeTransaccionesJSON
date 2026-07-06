# Normalizador de Transacciones

Aplicación de escritorio (Tkinter) que carga un JSON con transacciones de
múltiples fuentes (con nombres de campos y formatos distintos) y las
normaliza a un modelo común.

## Cómo ejecutarla

Requiere Python 3.9+ con Tkinter instalado (viene incluido en la mayoría de
instalaciones de Python; en Linux a veces hay que instalar el paquete del
sistema, por ejemplo `sudo apt install python3-tk`).

```bash
python3 transaction_normalizer.py
```

Se incluye `ejemplo_transacciones.json` con casos variados para probar la
aplicación (formatos de fecha distintos, símbolo de moneda en el monto,
monto con más de 4 cifras enteras, fecha inválida, etc.).

## Flujo de uso

1. **Cargar archivo JSON**: se valida que el archivo exista, no esté vacío
   y contenga una lista de objetos JSON bien formada.
2. **Selección de campos**: una ventana con checklist permite elegir qué
   campos del modelo se usarán para normalizar y exigir como obligatorios.
   Por defecto están todos marcados. Un campo desmarcado no se exige y no
   aparece en el resultado normalizado. Junto al campo **Monto** hay un
   control adicional (por defecto `4`) para configurar cuántas cifras
   enteras como máximo se admiten en el monto.
3. **Normalización**: cada transacción se procesa según los campos
   seleccionados. Si algún campo seleccionado no puede resolverse o no
   cumple el formato esperado, la transacción se marca como **inválida**
   junto con el motivo (o motivos) específico.
4. **Resultados**: desde la ventana principal se puede:
   - Ver **métricas** (totales, válidas/inválidas, conteo por estado,
     totales por moneda), con filtro por estado o por moneda sobre el
     listado de transacciones válidas.
   - Ver el **detalle de las inválidas** (motivo + datos originales) y
     exportarlas a un JSON.
   - **Exportar las transacciones válidas** normalizadas a un nuevo JSON.

## Reglas de normalización aplicadas

- **id**: se convierte a texto (string), sin transformación adicional.
- **amount**: máximo N cifras enteras (configurable en la ventana de
  selección de campos, 4 por defecto) y 2 decimales, sin separador de
  miles. Si el valor es un número entero se le agrega `.00`. Si la cadena
  trae una coma seguida de exactamente 2 dígitos al final (ej. `99,99`),
  se interpreta como separador decimal y se convierte a punto.
- **currency**: se toma de un campo de moneda explícito si existe; si no,
  se infiere a partir de un símbolo detectado en el monto (`$`, `€`, `£`,
  `¥`). Se normaliza a 3 letras mayúsculas (ISO 4217).
- **timestamp**: se acepta ISO-8601 (con o sin `Z`), `YYYY-MM-DD HH:MM:SS`
  y `DD/MM/YYYY HH:MM[:SS]`. El resultado siempre se expresa como
  `YYYY-MM-DDTHH:MM:SSZ`.
- **status**: se mapea mediante una tabla de equivalencias a
  `SUCCESSFUL | FAILED | PENDING` (ej. `completed`/`OK`/`success` →
  `SUCCESSFUL`). Un valor no reconocido invalida la transacción.
- **source**: se busca en campos tipo `type`, `method`, `source`, etc., y
  se mapea a `DEBIT | CREDIT | TRANSFER`. Si el campo no viene en los
  datos originales (y fue seleccionado en el checklist), la transacción
  se marca como inválida.

## Notas de diseño

- Las funciones de normalización (`normalize_amount`, `normalize_currency`,
  `normalize_timestamp`, `normalize_status`, `normalize_source`, etc.)
  son funciones puras, independientes de la interfaz gráfica, lo que
  facilita probarlas por separado (ver ejemplo de prueba manual más abajo).
- Todo el manejo de archivos y parsing de JSON está dentro de bloques
  `try/except`, mostrando siempre mensajes de error amigables mediante
  `messagebox`.
- El registro de actividad (carga de archivo, selección de campos,
  resultados del procesamiento, exportaciones) se muestra en tiempo real
  en la ventana principal usando el módulo estándar `logging`.

### Probar la lógica de normalización sin la interfaz

```python
from transaction_normalizer import normalize_transaction, ALL_FIELDS

registro = {"amount": "€99,99", "date": "2025-03-10T14:22:00Z", "result": "success"}
normalizado, es_valida, motivos = normalize_transaction(registro, set(ALL_FIELDS))
print(normalizado, es_valida, motivos)
```
