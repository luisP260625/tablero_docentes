import datetime

def registrar_acceso(usuario):
    """Registra el acceso en un archivo de texto con fecha y hora."""
    with open("data/accesos.log", "a") as archivo:
        fecha_hora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        archivo.write(f"{fecha_hora}, Usuario: {usuario}\n")

def contar_accesos(usuario):
    """Cuenta cuántas veces ha ingresado un usuario al sistema."""
    try:
        with open("data/accesos.log", "r") as archivo:
            registros = archivo.readlines()
        return sum(1 for linea in registros if f"Usuario: {usuario}" in linea)
    except FileNotFoundError:
        return 0  # Si el archivo no existe, el usuario no ha ingresado aún
