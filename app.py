import streamlit as st
import os

# ---------------------------
# 🔧 Debug: limpiar sesión (solo para desarrollo)
# st.session_state.clear()  # Descomenta si quieres forzar logout en cada carga
# ---------------------------

st.write("🛠️ Iniciando aplicación Streamlit...")

# Importaciones protegidas con try/except para ver errores
try:
    from data.loader import cargar_datos
    st.success("✅ Módulo loader cargado.")
except Exception as e:
    st.error(f"❌ Error al cargar loader.py: {e}")

try:
    from data.validator import validar_usuario
    st.success("✅ Módulo validator cargado.")
except Exception as e:
    st.error(f"❌ Error al cargar validator.py: {e}")

try:
    from data.logger import registrar_acceso, contar_accesos
    st.success("✅ Módulo logger cargado.")
except Exception as e:
    st.error(f"❌ Error al cargar logger.py: {e}")

try:
    from views.ranking_docentes_modulos import mostrar_ranking_por_plantel
    import views.no_competentes as vista_nc
    import views.comportamiento as vista_com
    import views.modulos_criticos as vista_mc
    import views.mostrar_estatal as vista_estatal
    import views.bitacora_conexiones as vista_bc
    st.success("✅ Vistas cargadas correctamente.")
except Exception as e:
    st.error(f"❌ Error al importar vistas: {e}")

# Configuración de la página
st.set_page_config(layout="wide", page_title="Dashboard de Competencias Académicas", page_icon="📊")

# Imagen inicial
ruta_imagen = "utils/ImagenDashDocentes.png"
if os.path.exists(ruta_imagen):
    st.image(ruta_imagen, use_container_width=True)
else:
    st.warning(f"⚠️ Imagen no encontrada: {ruta_imagen}")

# Inicializar estado de sesión si no está
if "logueado" not in st.session_state:
    st.session_state.update({
        "logueado": False,
        "plantel_usuario": None,
        "administrador": False
    })

# Botón de reinicio manual de sesión (solo para pruebas)
if st.sidebar.button("🔄 Reiniciar sesión (debug)"):
    for key in ["logueado", "plantel_usuario", "administrador"]:
        st.session_state.pop(key, None)
    st.rerun()

# Estilos visuales
fondo_color = "#f4f6fa" if not st.session_state.logueado else "white"
texto_color = "#b46b42" if not st.session_state.logueado else "black"

st.markdown(f"""
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
""", unsafe_allow_html=True)

# -----------------------------------------
# 🔐 FORMULARIO DE LOGIN
# -----------------------------------------
if not st.session_state.logueado:
    st.sidebar.title("🔒 Inicio de sesión")
    usuario = st.sidebar.text_input("Usuario")
    contrasena = st.sidebar.text_input("Contraseña", type="password")

    if st.sidebar.button("Iniciar sesión"):
        try:
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
                st.sidebar.error("❌ Acceso denegado. Verifica tus credenciales.")
        except Exception as e:
            st.sidebar.error(f"❌ Error en login: {e}")
else:
    # Botón de logout real
    if st.sidebar.button("Cerrar sesión"):
        for key in ["logueado", "plantel_usuario", "administrador"]:
            st.session_state.pop(key, None)
        st.rerun()

    # Si está logueado, cargar datos
    try:
        df, error = cargar_datos()
        if error:
            st.error(f"❌ Error al cargar datos: {error}")
            st.stop()
        else:
            st.success("✅ Datos cargados.")
            # Aquí puedes activar vistas reales, por ejemplo:
            # mostrar_ranking_por_plantel(df)
    except Exception as e:
        st.error(f"❌ Fallo en lógica de contenido: {e}")
