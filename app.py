import streamlit as st
from data.validator import validar_usuario
from data.loader import cargar_datos, cargar_semcaptura
from data.logger import registrar_acceso

# Importar vistas
from views.ranking_docentes_modulos import mostrar_ranking_por_plantel
from views.indicadores_academicos import mostrar_indicadores_academicos
import views.no_competentes as vista_nc
import views.comportamiento as vista_com
import views.modulos_criticos as vista_mc
import views.mostrar_estatal as vista_estatal
import views.bitacora_conexiones as vista_bc
import views.captura_docentes as vista_cd

st.set_page_config(page_title="Tablero Docente", layout="wide")

st.markdown("""
    <style>
    [data-testid="stToolbar"] > div:nth-child(n+2) {
        display: none !important;
    }
    </style>
""", unsafe_allow_html=True)

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
# Login
# ----------------------------
if not st.session_state.logueado:
    col1, col2 = st.columns([1, 2])

    with col1:
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

    with col2:
        try:
            st.image("utils/ImagenDashDocentes.png", use_container_width=True)
        except Exception:
            st.warning("⚠️ Imagen no disponible o no encontrada.")

    st.stop()

# ----------------------------
# Sidebar reorganizado
# ----------------------------
st.sidebar.success("✅ Sesión activa")

# Bienvenida personalizada
if st.session_state.administrador:
    st.sidebar.info("👤 Bienvenido: Administrador")
else:
    st.sidebar.info(f"👤 Bienvenido: Plantel {st.session_state.plantel_usuario}")

# Menú principal
if st.session_state.administrador:
    opciones = [
        "Docentes y Módulos",
        "Estatal Docentes y Módulos",
        "Docentes Seguimiento",
        "Módulos Seguimiento",
        "Indicadores Académicos",
        "Captura Docentes",
        "Bitácora de Conexiones"
    ]
else:
    opciones = [
        "Ranking por docentes y módulos",
        "Docentes y Módulos",
        "Docentes Seguimiento",
        "Módulos Seguimiento",
        "Indicadores Académicos",
        "Captura Docentes",
    ]

opcion = st.sidebar.selectbox("📂 MENÚ PRINCIPAL", opciones)

# Botón de cierre de sesión
if st.sidebar.button("🚪 Cerrar sesión"):
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
# Mostrar vistas
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

elif opcion == "Captura Docentes":
    df_sc, error_sc = cargar_semcaptura()
    if error_sc:
        st.error(f"❌ Error al cargar SemCaptura: {error_sc}")
        st.stop()

    vista_cd.mostrar(df_sc, st.session_state.plantel_usuario, st.session_state.administrador)

elif opcion == "Ranking por docentes y módulos":
    mostrar_ranking_por_plantel(df, st.session_state.plantel_usuario)

elif opcion == "Indicadores Académicos":
    mostrar_indicadores_academicos()  