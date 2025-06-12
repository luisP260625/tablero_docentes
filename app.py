import streamlit as st
from data.loader import cargar_datos
from data.validator import validar_usuario
from data.logger import registrar_acceso, contar_accesos
import os

# Vistas
import views.no_competentes as vista_nc
import views.comportamiento as vista_com
import views.modulos_criticos as vista_mc
import views.mostrar_estatal as vista_estatal
import views.bitacora_conexiones as vista_bc

# Configuración de la página
st.set_page_config(layout="wide", page_title="Dashboard de Competencias Académicas", page_icon="📊")

# Estilos dinámicos
if "logueado" not in st.session_state or not st.session_state.logueado:
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

# Mostrar imagen antes del login
if "logueado" not in st.session_state or not st.session_state.logueado:
    ruta_imagen = "utils/ImagenDashDocentes.png"
    if os.path.exists(ruta_imagen):
        st.image(ruta_imagen, use_container_width=True)
    else:
        st.warning("⚠️ No se encontró la imagen en 'utils/ImagenDashDocentes.png'.")

    #st.markdown("<h1 style='text-align: center; color: #b46b42;'>SEGUIMIENTO A DOCENTES</h1>", unsafe_allow_html=True)

# Cargar datos
df, error = cargar_datos()
if error:
    st.error(f"Error al cargar los datos: {error}")
    st.stop()

# Inicializar sesión
if "logueado" not in st.session_state:
    st.session_state.update({
        "logueado": False,
        "plantel_usuario": None,
        "administrador": False
    })

# Pantalla de inicio de sesión
if not st.session_state.logueado:
    st.sidebar.title("🔒 Inicio de sesión")
    usuario = st.sidebar.text_input("Usuario")
    contrasena = st.sidebar.text_input("Contraseña", type="password")

    if st.sidebar.button("Iniciar sesión"):
        ok, plantel, es_admin = validar_usuario(usuario, contrasena)
        if ok:
            registrar_acceso(usuario)
            num_accesos = contar_accesos(usuario)
            st.sidebar.info(f"{usuario} ha ingresado {num_accesos} veces")

            st.session_state.update({
                "logueado": True,
                "plantel_usuario": plantel,
                "administrador": es_admin
            })
            st.rerun()
        else:
            st.sidebar.error("Acceso denegado. Verifica tus credenciales.")

# Usuario logueado
else:
    if st.sidebar.button("Cerrar sesión"):
        for key in ["logueado", "plantel_usuario", "administrador"]:
            st.session_state.pop(key, None)
        st.rerun()

    # Menú dinámico
    if st.session_state.administrador:
        opciones_menu = [
            "No Competentes",
            "Estatal de No Competencia",
            "Comportamiento Semanal de Docentes",
            "Módulos Críticos y Recomendaciones",
            "Bitácora de Conexiones"
        ]
    else:
        opciones_menu = [
            "No Competentes",
            "Comportamiento Semanal de Docentes",
            "Módulos Críticos y Recomendaciones"
        ]

    opcion = st.sidebar.selectbox("📌 Menú", opciones_menu)

    # Renderizado de vista
    if opcion == "No Competentes":
        vista_nc.mostrar(df, st.session_state.plantel_usuario, st.session_state.administrador)

    elif opcion == "Estatal de No Competencia" and st.session_state.administrador:
        vista_estatal.mostrar_estatal(df)

    elif opcion == "Comportamiento Semanal de Docentes":
        vista_com.mostrar(df, st.session_state.plantel_usuario, st.session_state.administrador)

    elif opcion == "Módulos Críticos y Recomendaciones":
        vista_mc.mostrar(df, st.session_state.plantel_usuario, st.session_state.administrador)

    elif opcion == "Bitácora de Conexiones" and st.session_state.administrador:
        vista_bc.mostrar()
