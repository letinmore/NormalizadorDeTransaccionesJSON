# Documento de reflexión técnica

## Definición de la tarea usada con la IA

Desarrollar una aplicación para escritorio en Python que analice un archivo JSON que contiene transacciones provenientes de múltiples fuentes, y pueden tener distintos nombres de campos y valores, por ejemplo:

```json
[
    {
        "id": "tx_001",
        "amount": "100.50",
        "currency": "USD",
        "timestamp": "2025-03-10 14:22:00",
        "status": "completed"
    },
    {
        "transaction_id": 204,
        "total": 10050,
        "currency_code": "usd",
        "created_at": "10/03/2025 14:22",
        "state": "OK"
    },
    {
        "ref": "A-77",
        "amount": "€99,99",
        "date": "2025-03-10T14:22:00Z",
        "result": "success"
    }
]
```

Las transacciones deben normalizarse a un formato común siguiendo un modelo como este (nombre y tipo de datos o valor esperado en el campo):

```json
{
    "id": "string",
    "amount": 99.99,
    "currency": "USD ",
    "timestamp": "ISO-8601",
    "status": "SUCCESSFUL | FAILED | PENDING",
    "source": "DEBIT | CREDIT | TRANSFER"
}
```

El proceso debe ser más o menos así:

1. Cargar JSON que elija el usuario.
2. Validar archivo a nivel básico (si está vacío, o no es un JSON bien estructurado).
3. Mostrar ventana preguntando cuáles campos se van a usar para la normalización (estilo checklist), por defecto debe estar seleccionados todos los campos.
4. Leer el archivo y normalizar cada transacción de acuerdo a los campos seleccionados antes:
    - a. Para la moneda (campo `"currency"`), debe identificarse si hay símbolo en la cantidad o en un campo separado y tomarse el valor de ahí para el valor del campo normalizado.
    - b. Debe admitirse como máximo 4 cifras enteras y 2 decimales en la cantidad o monto, sin comas separando miles. Si es un número entero debe agregarse `"00"` como parte decimal.
    - c. Si hay coma presente en la cantidad y dos decimales a la derecha de ella, asumir que es separador de decimales y convertirla en punto decimal.
    - d. La fecha debe validarse y transformarse al tipo indicado en el modelo.
    - e. Si hay símbolo de moneda junto a la cantidad, al normalizar solo debe dejarse la cantidad.
5. Identificar transacciones inválidas o incompletas y agregarlas a una lista para después contarlas y dar la opción de mostrarlas en una nueva ventana y exportarlas a un nuevo JSON.
6. Generar métricas: total de transacciones procesadas, total de transacciones válidas vs inválidas, conteo por estado y totales por moneda. En la ventana donde se muestren, agregar opciones para listar, filtrar y visualizar métricas.

### Detalles adicionales

Para la interfaz gráfica debe usarse Tkinter, y el código debe estar en un solo script, además, debe estar estructurado siguiendo las prácticas recomendadas, debe usar bloques `try/except` donde sea necesario y debe mostrar mensajes amigables con el usuario.

## Ajustes realizados sobre sugerencias de IA

1. Se agregó la cantidad de cifras como elemento variable que puede cambiar el usuario en la interfaz de selección de campos.
2. Se definió la acción a realizar si el campo `"status"` no se encuentra en la transacción.
3. Se modificó el comportamiento al dar la opción al usuario para elegir campos para normalizar.
