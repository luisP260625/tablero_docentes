import streamlit as st
import os
from data.validator import validar_usuario
from data.loader import cargar_datos
from data.logger import registrar_acceso, contar_accesos

# Importar vistas
from views.ranking_docentes_modulos import mostrar_ranking_por_plantel
import views.no_competentes as vista_nc
import views.comportamiento as vista_com
import views.modulos_criticos as vista_mc
import views.mostrar_estatal as vista_estatal
import views.bitacora_conexiones as vista_bc

# ----------------------------
# Inicializar sesión
# ----------------------------
if "logueado" not in st.session_state:
    st.session_state.update({
        "logueado": False,
        "plantel_usuario": None,
        "administrador": False
    })

# ----------------------------
# Estilos dinámicos
# ----------------------------
if not st.session_state.logueado:
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

# ----------------------------
# Login
# ----------------------------
if not st.session_state.logueado:
    st.title("🔐 Inicio de sesión")

    usuario = st.text_input("Usuario")
    contrasena = st.text_input("Contraseña", type="password")

    if st.button("Iniciar sesión"):
        ok, plantel, es_admin = validar_usuario(usuario, contrasena)
        if ok:
            st.session_state.update({
                "logueado": True,
                "plantel_usuario": plantel,
                "administrador": es_admin
            })
            registrar_acceso(usuario)
            st.success("✅ ¡Sesión iniciada!")
            st.rerun()
        else:
            st.error("❌ Credenciales incorrectas")
    st.stop()

# ----------------------------
# Cierre de sesión
# ----------------------------
st.sidebar.success("✅ Sesión activa")
st.sidebar.info(f"👤 {'Administrador' if st.session_state.administrador else f'Plantel: {st.session_state.plantel_usuario}'}")

if st.sidebar.button("Cerrar sesión"):
    for key in ["logueado", "plantel_usuario", "administrador"]:
        st.session_state.pop(key, None)
    st.rerun()

# ----------------------------
# Cargar datos
# ----------------------------
df, error = cargar_datos()
if error:
    st.error(f"❌ Error al cargar los datos: {error}")
    st.stop()

# ----------------------------
# Menú según rol
# ----------------------------
if st.session_state.administrador:
    opcion = st.sidebar.radio("Menú administrador", [
        "Docentes y Módulos",
        "Estatal Docentes y Módulos",
        "Docentes Seguimiento",
        "Módulos Seguimiento",
        "Bitácora de Conexiones"
    ])
else:
    opcion = st.sidebar.radio("Menú plantel", [
        "Docentes y Módulos",
        "Docentes Seguimiento",
        "Módulos Seguimiento",
        "Ranking por docentes y módulos"
    ])

# ----------------------------
# Mostrar vistas según opción
# ----------------------------
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
    mostrar_ranking_por_plantel(df, st.session_state.plantel_usuario)
