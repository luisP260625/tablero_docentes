import streamlit as st
from data.loader import cargar_datos
from data.validator import validar_usuario
from data.logger import registrar_acceso, contar_accesos  # Importar funciones para la bitácora
import views.no_competentes as vista_nc
import views.comportamiento as vista_com
import views.modulos_criticos as vista_mc

st.set_page_config(layout="wide", page_title="Dashboard de Competencias Académicas", page_icon="📊")

# Ocultar elementos de Streamlit
hide_streamlit_style = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# Cargar datos
df, error = cargar_datos()
if error:
    st.error(f"Error: {error}")
    st.stop()

# Inicializar variables de sesión
if "logueado" not in st.session_state:
    st.session_state.update({"logueado": False, "plantel_usuario": None, "administrador": False})

# Inicio de sesión
if not st.session_state.logueado:
    st.sidebar.title("🔒 Inicio de sesión")
    usuario = st.sidebar.text_input("Usuario")
    contrasena = st.sidebar.text_input("Contraseña", type="password")

    if st.sidebar.button("Iniciar sesión"):
        ok, plantel = validar_usuario(usuario, contrasena)
        if ok:
            registrar_acceso(usuario)  # Registrar acceso en bitácora
            num_accesos = contar_accesos(usuario)  # Contar accesos previos
            st.sidebar.info(f"{usuario} ha ingresado {num_accesos} veces")  # Mostrar en UI
            
            st.session_state.update({
                "logueado": True,
                "plantel_usuario": plantel,
                "administrador": usuario.lower() == "admin"
            })
            st.rerun()
        else:
            st.sidebar.error("Acceso denegado.")

# Cierre de sesión
else:
    if st.sidebar.button("Cerrar sesión"):
        for key in ["logueado", "plantel_usuario", "administrador"]:
            st.session_state.pop(key, None)
        st.rerun()

    # Definir menú según tipo de usuario
    if st.session_state.administrador:
        opciones_menu = [
            "No Competentes",
            "Comportamiento Semanal de Docentes",
            "Módulos Críticos y Recomendaciones"
        ]
    else:
        opciones_menu = [
            "No Competentes",
            "Comportamiento Semanal de Docentes",
            "Módulos Críticos y Recomendaciones"
        ]

    opcion = st.sidebar.selectbox("📌 Menú", opciones_menu)

    # Renderizar vistas según la opción seleccionada
    if opcion == "No Competentes":
        vista_nc.mostrar(df, st.session_state.plantel_usuario, st.session_state.administrador)
    elif opcion == "Comportamiento Semanal de Docentes":
        vista_com.mostrar(df, st.session_state.plantel_usuario, st.session_state.administrador)
    elif opcion == "Módulos Críticos y Recomendaciones":
        vista_mc.mostrar(df, st.session_state.plantel_usuario, st.session_state.administrador)