import streamlit as st
import os

# Importación de funciones y vistas
from data.loader import cargar_datos
from data.validator import validar_usuario
from data.logger import registrar_acceso, contar_accesos
from views.ranking_docentes_modulos import mostrar_ranking_por_plantel

# Vistas
import views.no_competentes as vista_nc
import views.comportamiento as vista_com
import views.modulos_criticos as vista_mc
import views.mostrar_estatal as vista_estatal
import views.bitacora_conexiones as vista_bc

# Configuración de la página
st.set_page_config(layout="wide", page_title="Dashboard de Competencias Académicas", page_icon="📊")

# Estilos dinámicos
if not st.session_state.get("logueado", False):
    fondo_color = "#f4f6fa"
    texto_color = "#b46b42"
else:
    fondo_color = "white"
    texto_color = "black"

custom_styles = f"""
    <style>
    #MainMenu, footer, header {{visibility: hidden;}}
    .stApp {{
        background-color: {fondo_color};
    }}
    .block-container {{
        padding-top: 2rem;
        padding-bottom: 2rem;
        color: {texto_color};
    }}
    section[data-testid="stSidebar"] {{
        width: 320px !important;
    }}
    </style>
"""
st.markdown(custom_styles, unsafe_allow_html=True)

# Inicializar sesión
if "logueado" not in st.session_state:
    st.session_state.update({
        "logueado": False,
        "plantel_usuario": None,
        "administrador": False
    })

# Mostrar solo formulario de login si no está logueado
if not st.session_state.logueado:
    st.sidebar.title("🔒 Inicio de sesión")
    usuario = st.sidebar.text_input("Usuario")
    contrasena = st.sidebar.text_input("Contraseña", type="password")

    if st.sidebar.button("Iniciar sesión"):
        ok, plantel, es_admin = validar_usuario(usuario, contrasena)
        if ok:
            registrar_acceso(usuario)
            num_accesos = contar_accesos(usuario)

            st.session_state.update({
                "logueado": True,
                "plantel_usuario": plantel,
                "administrador": es_admin
            })
            st.rerun()
        else:
            st.sidebar.error("Acceso denegado. Verifica tus credenciales.")
    st.stop()  # Evita mostrar cualquier otra cosa si no ha iniciado sesión

# Usuario logueado
if st.session_state.logueado:
    # Botón de cerrar sesión
    if st.sidebar.button("Cerrar sesión"):
        st.session_state.clear()
        st.rerun()

    # Cargar datos solo si el usuario está logueado
    df, error = cargar_datos()
    if error:
        st.error(f"Error al cargar los datos: {error}")
        st.stop()

    # Menú dinámico según si es administrador
    if st.session_state.administrador:
        opciones_menu = [
            "Docentes y Módulos",
            "Estatal Docentes y Módulos",
            "Docentes Seguimiento",
            "Módulos Seguimiento",
            "Bitácora de Conexiones"
        ]
    else:
        opciones_menu = [
            "Docentes y Módulos",
            "Docentes Seguimiento",
            "Módulos Seguimiento",
            "Ranking por docentes y módulos"
        ]

    opcion = st.sidebar.selectbox("📌 Menú", opciones_menu)

    # Renderizado de vista
    if opcion == "Docentes y Módulos":
        vista_nc.mostrar(df, st.session_state.plantel_usuario, st.session_state.administrador)

    elif opcion == "Estatal Docentes y Módulos" and st.session_state.administrador:
        vista_estatal.mostrar_estatal(df)

    elif opcion == "Docentes Seguimiento":
        vista_com.mostrar(df, st.session_state.plantel_usuario, st.session_state.administrador)

    elif opcion == "Módulos Seguimiento":
        vista_mc.mostrar(df, st.session_state.plantel_usuario, st.session_state.administrador)

    elif opcion == "Bitácora de Conexiones" and st.session_state.administrador:
        vista_bc.mostrar()

    elif opcion == "Ranking por docentes y módulos":
        mostrar_ranking_por_plantel(df, st.session_state["plantel_usuario"])
