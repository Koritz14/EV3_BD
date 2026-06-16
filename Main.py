"""
Aplicación de consola - Consultas avanzadas con MongoDB
Unidad 3: Búsqueda avanzada con MongoDB
"""

import json
import os
import re
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure


# ─────────────────────────────────────────────
#  CONEXIÓN A MONGODB
# ─────────────────────────────────────────────
def conectar():
    """
    Establece conexión con MongoDB Compass (local).
    Cambia la URI si tu instancia usa otro puerto o autenticación.
    """
    try:
        cliente = MongoClient(
            "mongodb://localhost:27017/",
            serverSelectionTimeoutMS=3000
        )
        cliente.admin.command("ping")
        print("✅ Conexión exitosa a MongoDB\n")
        return cliente
    except ConnectionFailure:
        msg = "❌ No se pudo conectar a MongoDB. "
        msg += "Asegúrate de que Compass esté activo."
        print(msg)
        return None


# ─────────────────────────────────────────────
#  CARGA DE DATOS DESDE JSON
# ─────────────────────────────────────────────

def limpiar_documento(doc):
    """
    Los JSON de evaluación suelen venir con valores tipo ISODate("...") que
    no son JSON estándar. Esta función los convierte a objetos datetime de
    Python para que MongoDB los almacene correctamente como tipo Date.
    """
    doc_limpio = {}
    for clave, valor in doc.items():
        if isinstance(valor, str) and valor.startswith("ISODate("):
            # Extrae la fecha: ISODate("2025-08-14") → "2025-08-14"
            fecha_str = valor[9:-2]  # quita ISODate(" y ")
            try:
                doc_limpio[clave] = datetime.strptime(fecha_str, "%Y-%m-%d")
            except ValueError:
                # si no parsea, lo deja como string
                doc_limpio[clave] = valor
        elif isinstance(valor, list):
            doc_limpio[clave] = [
                limpiar_documento(item)
                if isinstance(item, dict)
                else item
                for item in valor
            ]
        elif isinstance(valor, dict):
            doc_limpio[clave] = limpiar_documento(valor)
        else:
            doc_limpio[clave] = valor
    return doc_limpio


def limpiar_sintaxis_json(contenido):
    """
    Corrige errores de sintaxis comunes en JSON generados manualmente
    o exportados desde MongoDB shell:

      1. ISODate("...")        → "ISODate(...)"  (valor temporal)
      2. "clave":,            → "clave": null,   (valor vacío por error)
      3. "clave": value,\n}   → sin coma colgante antes de } o ]
      4. "),                  → ",               (paréntesis en lugar de)
      5. falta coma entre pares  "valor"\n"clave" → "valor",\n"clave"
      6. Punto y coma final   ];  → ]
    """

    # 1. ISODate("2025-08-14") → "ISODate(2025-08-14)"
    contenido = re.sub(r'ISODate\("([^"]+)"\)', r'"ISODate(\1)"', contenido)

    # 2. "campo":, → "campo": null,
    contenido = re.sub(r':\s*,', ': null,', contenido)

    # 3. Paréntesis de cierre pegado a comilla de _id: "33333333-3")
    #    Lo reemplazamos por comilla normal
    contenido = re.sub(r'("[\w\-]+")\)', r'\1"', contenido)
    # También el caso "33333333-3") → "33333333-3"
    contenido = re.sub(r'\)\s*,', '",', contenido)

    # 4. Coma faltante entre valor y siguiente clave:
    pattern1 = r'("(?:[^"\\]|\\.)*")\s*\n(\s*")'
    contenido = re.sub(pattern1, r'\1,\n\2', contenido)
    # Número o true/false seguido de clave sin coma
    pattern2 = r'([\d\.]+|true|false)\s*\n(\s*")'
    contenido = re.sub(pattern2, r'\1,\n\2', contenido)

    # 5. Trailing commas antes de } o ]  →  eliminarlas
    contenido = re.sub(r',(\s*[}\]])', r'\1', contenido)

    # 6. Punto y coma al final del archivo (estilo MongoDB shell)
    contenido = re.sub(r';\s*$', '', contenido.strip())

    return contenido


def cargar_json_a_mongo(db, ruta_archivo, nombre_coleccion):
    """
    Lee un archivo .json, limpia errores de sintaxis comunes y sube los
    documentos a la colección indicada.
    """
    if not os.path.exists(ruta_archivo):
        print(f"  ❌ Archivo no encontrado: {ruta_archivo}")
        return

    with open(ruta_archivo, "r", encoding="utf-8") as f:
        contenido = f.read()

    contenido = limpiar_sintaxis_json(contenido)

    try:
        datos = json.loads(contenido)
    except json.JSONDecodeError as e:
        # Mostrar contexto del error para facilitar corrección manual
        lineas = contenido.splitlines()
        linea_err = e.lineno - 1
        msg = f"  ❌ Error de sintaxis en línea {e.lineno}, "
        msg += f"columna {e.colno}: {e.msg}"
        print(msg)
        print("  Contexto:")
        for i in range(max(0, linea_err - 2), min(len(lineas), linea_err + 3)):
            marca = ">>>" if i == linea_err else "   "
            print(f"  {marca} {i+1}: {lineas[i]}")
        print("\n  Corrige el archivo JSON y vuelve a intentarlo.")
        return

    if not isinstance(datos, list):
        datos = [datos]   # si viene un objeto solo, lo envolvemos en lista

    # Si ya hay documentos en la colección, preguntar
    coleccion = db[nombre_coleccion]
    cantidad_actual = coleccion.count_documents({})
    if cantidad_actual > 0:
        prompt = f"  ⚠️  La colección '{nombre_coleccion}' "
        prompt += f"ya tiene {cantidad_actual} documento(s). "
        prompt += "¿Reemplazar? (s/n): "
        respuesta = input(prompt).strip().lower()
        if respuesta == "s":
            coleccion.drop()
            print(f"  🗑️  Colección '{nombre_coleccion}' eliminada.")
        else:
            print("  ↩️  Carga cancelada.")
            return

    # Limpiar ISODate y subir
    datos_limpios = [limpiar_documento(doc) for doc in datos]
    resultado = coleccion.insert_many(datos_limpios)
    cantidad = len(resultado.inserted_ids)
    print(f"  ✅ {cantidad} documento(s) insertados "
          f"en '{nombre_coleccion}'.")


def detectar_json_locales():
    """
    Busca todos los archivos .json en la misma carpeta donde está el script.
    Retorna lista de rutas absolutas ordenadas alfabéticamente.
    """
    carpeta = os.path.dirname(os.path.abspath(__file__))
    archivos = [
        os.path.join(carpeta, f)
        for f in os.listdir(carpeta)
        if f.lower().endswith(".json")
    ]
    return sorted(archivos)


def menu_carga(db):
    """
    Detecta automáticamente los .json en la carpeta del script,
    los lista y permite cargar cada uno en una colección con el
    nombre que el usuario elija. Soporta 1, 2 o más archivos.
    """
    print("\n── CARGA DE DATOS DESDE JSON ───────────────────────")

    archivos = detectar_json_locales()

    if not archivos:
        msg = "  ⚠️  No se encontraron archivos .json "
        msg += "en la carpeta del script."
        print(msg)
        ruta = os.path.dirname(os.path.abspath(__file__))
        print(f"  Carpeta revisada: {ruta}")
        return

    print(f"  Se encontraron {len(archivos)} archivo(s):\n")
    for i, ruta in enumerate(archivos, 1):
        nombre = os.path.basename(ruta)
        print(f"    [{i}] {nombre}")

    msg = "\n  Para cada archivo indica el nombre de "
    msg += "colección donde cargarlo."
    print(msg)
    print("  Presiona Enter para omitir un archivo.\n")

    for ruta in archivos:
        nombre_archivo = os.path.basename(ruta)
        prompt = f"  '{nombre_archivo}' → nombre de "
        prompt += "colección (Enter omite): "
        nombre_col = input(prompt).strip()

        if not nombre_col:
            print("  ↩️  Omitido.\n")
            continue

        print(f"  Cargando en colección '{nombre_col}'...")
        cargar_json_a_mongo(db, ruta, nombre_col)
        print()


# ─────────────────────────────────────────────
#  FUNCIONES DE CONSULTA
# ─────────────────────────────────────────────

def consulta_1_clientes_inactivos(db):
    """
    Criterio 3.1.1 - Filtros y condiciones
    Obtener listado de clientes inactivos con _id, nombre y fecha_registro.

    Consulta MongoDB equivalente:
        db.clientes.find(
            { "Activo": false },
            { "_id": 1, "nombre": 1, "fecha_registro": 1 }
        )
    """
    print("\n── Clientes INACTIVOS ──────────────────────────────")

    proyeccion = {"_id": 1, "nombre": 1, "fecha_registro": 1}
    resultados = db.clientes.find({"Activo": False}, proyeccion)

    encontrados = 0
    for cliente in resultados:
        fecha = cliente.get("fecha_registro")
        if isinstance(fecha, datetime):
            fecha = fecha.strftime("%Y-%m-%d")
        print(f"  ID            : {cliente['_id']}")
        print(f"  Nombre        : {cliente['nombre']}")
        print(f"  Fecha registro: {fecha or 'N/A'}")
        print("  " + "-" * 40)
        encontrados += 1

    if encontrados == 0:
        print("  No se encontraron clientes inactivos.")
    else:
        print(f"  Total encontrados: {encontrados}")


def consulta_2_buscar_por_regex(db, texto_busqueda):
    """
    Criterio 3.1.2 - Expresiones regulares
    Buscar clientes por nombre parcial O por dominio de correo.
    La búsqueda NO es sensible a mayúsculas/minúsculas (opción 'i').

    Consulta MongoDB equivalente:
        db.clientes.find({
            $or: [
                { "nombre": { $regex: <texto>, $options: "i" } },
                { "email":  { $regex: <texto>, $options: "i" } }
            ]
        })
    """
    print(f"\n── Búsqueda regex: '{texto_busqueda}' ─────────────────")

    patron = {"$regex": texto_busqueda, "$options": "i"}
    filtro = {
        "$or": [
            {"nombre": patron},
            {"email":  patron}
        ]
    }

    resultados = db.clientes.find(filtro)
    encontrados = 0

    for cliente in resultados:
        print(f"  ID    : {cliente['_id']}")
        print(f"  Nombre: {cliente['nombre']}")
        print(f"  Email : {cliente['email']}")
        print("  " + "-" * 40)
        encontrados += 1

    if encontrados == 0:
        print("  No se encontraron coincidencias.")
    else:
        print(f"  Total encontrados: {encontrados}")


def consulta_3_cliente_tiene_producto(db, cliente_id, producto_id=101):
    """
    Criterio 3.1.3 - Consultas en subdocumentos / iteración
    Verifica si un cliente tiene pedidos que incluyan el producto_id indicado.
    Itera sobre el array 'productos' de cada pedido (subdocumento).

    Consulta MongoDB equivalente:
        db.pedidos.find({
            "cliente_id": <cliente_id>,
            "productos.producto_id": <producto_id>
        })
    """
    msg = f"\n── Pedidos de cliente '{cliente_id}' "
    msg += f"con producto {producto_id} ──"
    print(msg)

    filtro = {
        "cliente_id": cliente_id,
        "productos.producto_id": producto_id
    }

    resultados = list(db.pedidos.find(filtro))

    if not resultados:
        msg = "  El cliente NO tiene pedidos "
        msg += f"con el producto {producto_id}."
        print(msg)
    else:
        cantidad = len(resultados)
        msg = f"  ✅ El cliente SÍ tiene {cantidad} "
        msg += f"pedido(s) con el producto {producto_id}:"
        print(msg)
        for pedido in resultados:
            fecha = pedido.get("fecha_pedido")
            if isinstance(fecha, datetime):
                fecha = fecha.strftime("%Y-%m-%d")
            print(f"    Pedido ID : {pedido['_id']}")
            print(f"    Fecha     : {fecha or 'N/A'}")
            print(f"    Total     : ${pedido.get('monto_total', 0):.2f}")
            for prod in pedido.get("productos", []):
                if prod["producto_id"] == producto_id:
                    msg = f"    → Producto {prod['producto_id']}: "
                    msg += f"cantidad={prod['cantidad']}, "
                    msg += f"precio=${prod['precio']:.2f}"
                    print(msg)
            print("  " + "-" * 40)


def consulta_4_cliente_mayor_pedidos(db):
    """
    Criterio 3.1.4 - Organización de comandos / $lookup / agregación
    Encuentra el cliente con mayor número de pedidos usando $lookup y $group.

    Consulta MongoDB equivalente (pipeline de agregación):
        db.pedidos.aggregate([
            { $group: { _id: "$cliente_id", total_pedidos: { $sum: 1 } } },
            { $sort:  { total_pedidos: -1 } },
            { $limit: 1 },
            { $lookup: {
                from: "clientes",
                localField: "_id",
                foreignField: "_id",
                as: "info_cliente"
            }},
            { $unwind: "$info_cliente" }
        ])
    """
    print("\n── Cliente con MAYOR número de pedidos ────────────────")

    pipeline = [
        {"$group": {"_id": "$cliente_id", "total_pedidos": {"$sum": 1}}},
        {"$sort": {"total_pedidos": -1}},
        {"$limit": 1},
        {"$lookup": {
            "from": "clientes",
            "localField": "_id",
            "foreignField": "_id",
            "as": "info_cliente"
        }},
        {"$unwind": "$info_cliente"}
    ]

    resultados = list(db.pedidos.aggregate(pipeline))

    if not resultados:
        print("  No se encontraron datos.")
    else:
        r = resultados[0]
        info = r["info_cliente"]
        print(f"  ID Cliente    : {r['_id']}")
        print(f"  Nombre        : {info.get('nombre', 'N/A')}")
        print(f"  Email         : {info.get('email', 'N/A')}")
        print(f"  Total pedidos : {r['total_pedidos']}")


def consulta_5_cliente_activo(db, cliente_id):

    print(f"\n── Verificar si cliente '{cliente_id}' está ACTIVO ──")

    filtro = {"_id": cliente_id, "Activo": True}
    resultado = db.clientes.find_one(filtro)

    if resultado:
        print("  El cliente está ACTIVO.")
        print(f"  Nombre: {resultado.get('nombre', 'N/A')}")
        print(f"  Email : {resultado.get('email', 'N/A')}")
    else:
        print("  El cliente NO está activo o no existe.")


# ─────────────────────────────────────────────
#  MENÚ PRINCIPAL
# ─────────────────────────────────────────────

def menu(db):
    opciones = {
        "0": "Cargar datos desde archivos JSON → MongoDB",
        "1": "Listar clientes inactivos",
        "2": "Buscar clientes por nombre o dominio de email (regex)",
        "3": "Verificar si un cliente tiene el producto 101",
        "4": "Cliente con mayor número de pedidos",
        "5": "Consultar cliente activo",
        "9": "Salir"
    }

    while True:
        print("\n══════════════════════════════════════════")
        print("       SISTEMA DE CONSULTAS MONGODB       ")
        print("══════════════════════════════════════════")
        for k, v in opciones.items():
            print(f"  [{k}] {v}")
        print("══════════════════════════════════════════")

        opcion = input("Selecciona una opción: ").strip()

        if opcion == "0":
            menu_carga(db)

        elif opcion == "1":
            consulta_1_clientes_inactivos(db)

        elif opcion == "2":
            prompt = "Ingresa nombre parcial o dominio "
            prompt += "(@gmail.com, etc.): "
            texto = input(prompt).strip()
            if texto:
                consulta_2_buscar_por_regex(db, texto)
            else:
                print("  ⚠️  Debes ingresar un texto de búsqueda.")

        elif opcion == "3":
            prompt = "Ingresa el ID del cliente "
            prompt += "(ej: 11111111-1): "
            cliente_id = input(prompt).strip()
            if cliente_id:
                consulta_3_cliente_tiene_producto(
                    db, cliente_id, producto_id=101
                )
            else:
                print("  ⚠️  Debes ingresar un ID de cliente.")

        elif opcion == "4":
            consulta_4_cliente_mayor_pedidos(db)

        elif opcion == "5":
            prompt = "Ingresa el ID del cliente "
            prompt += "(ej: 11111111-1): "
            cliente_id = input(prompt).strip()
            if cliente_id:
                consulta_5_cliente_activo(db, cliente_id)
            else:
                print("  ⚠️  Debes ingresar un ID de cliente.")

        elif opcion == "9":
            print("\n👋 Saliendo del programa. ¡Hasta pronto!\n")
            break

        else:
            print("  ⚠️  Opción no válida. Intenta de nuevo.")


# ─────────────────────────────────────────────
#  PUNTO DE ENTRADA
# ─────────────────────────────────────────────

if __name__ == "__main__":
    cliente_mongo = conectar()
    if cliente_mongo:
        # Nombre de BD automático del nombre de carpeta
        nombre_bd = os.path.basename(
            os.path.dirname(os.path.abspath(__file__))
        )
        print(f"📂 Base de datos: '{nombre_bd}'")
        base_datos = cliente_mongo[nombre_bd]
        menu(base_datos)
        cliente_mongo.close()
