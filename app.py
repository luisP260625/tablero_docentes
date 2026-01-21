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
import views.historico_indicadores as vista_hi

# ✅ NUEVO módulo
from views.estudiantes_por_grupo import mostrar_estudiantes_por_grupo

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
        "usuario": None,
        "plantel_usuario": None,
        "permisos": set(),
        # compatibilidad con vistas actuales: admin = puede ver todo (scope)
        "administrador": False,
    })


def _menu_por_permisos(perms: set[str], plantel: str | None) -> list[str]:
    """
    Permisos especiales tipo "perfil":
      - MENU_TODOS
      - MENU_PLANTEL
      - MENU_SOLO_HISTORICO
    Permisos específicos por opción (opcionales):
      - MENU_HISTORICO_INDICADORES
      - MENU_INDICADORES_ACADEMICOS
      - MENU_BITACORA_CONEXIONES
      - MENU_ESTUDIANTES_POR_GRUPO
      - etc.
    """
    # Menús base (como estaba tu app)
    menu_plantel = [
        "Ranking por docentes y módulos",
        "Docentes y Módulos",
        "Docentes Seguimiento",
        "Módulos Seguimiento",
        "Indicadores Académicos",
        "Histórico de Indicadores",
        "Captura Docentes",
        # ✅ NUEVO
        "Estudiantes por Grupo",
    ]

    menu_admin = [
        "Docentes y Módulos",
        "Estatal Docentes y Módulos",
        "Docentes Seguimiento",
        "Módulos Seguimiento",
        "Indicadores Académicos",
        "Histórico de Indicadores",
        "Captura Docentes",
        "Bitácora de Conexiones",
        # ✅ NUEVO
        "Estudiantes por Grupo",
    ]

    allowed = set()

    # Perfiles
    if "MENU_TODOS" in perms:
        allowed.update(menu_admin)
    if "MENU_PLANTEL" in perms:
        allowed.update(menu_plantel)
    if "MENU_SOLO_HISTORICO" in perms:
        allowed.add("Histórico de Indicadores")

    # Permisos específicos (por si decides usarlos)
    if "MENU_HISTORICO_INDICADORES" in perms:
        allowed.add("Histórico de Indicadores")
    if "MENU_INDICADORES_ACADEMICOS" in perms:
        allowed.add("Indicadores Académicos")
    if "MENU_BITACORA_CONEXIONES" in perms:
        allowed.add("Bitácora de Conexiones")
    if "MENU_ESTATAL_DOCENTES_MODULOS" in perms:
        allowed.add("Estatal Docentes y Módulos")
    if "MENU_CAPTURA_DOCENTES" in perms:
        allowed.add("Captura Docentes")

    # ✅ NUEVO permiso específico
    if "MENU_ESTUDIANTES_POR_GRUPO" in perms:
        allowed.add("Estudiantes por Grupo")

    # Si no le diste permisos de menú, fallback práctico:
    # - si trae plantel -> menú plantel
    if not allowed and plantel:
        allowed.update(menu_plantel)

    # Orden final (para que el selectbox se vea bonito)
    order = [
        "Ranking por docentes y módulos",
        "Docentes y Módulos",
        "Estatal Docentes y Módulos",
        "Docentes Seguimiento",
        "Módulos Seguimiento",
        "Indicadores Académicos",
        "Histórico de Indicadores",
        "Captura Docentes",
        "Bitácora de Conexiones",
        # ✅ NUEVO
        "Estudiantes por Grupo",
    ]
    return [x for x in order if x in allowed]


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
            ok, plantel, perms, username = validar_usuario(usuario, contrasena)
            if ok:
                st.session_state.update({
                    "logueado": True,
                    "usuario": username,
                    "plantel_usuario": plantel,
                    "permisos": perms,
                    # compatibilidad: admin scope
                    "administrador": ("MENU_TODOS" in perms),
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
# Sidebar
# ----------------------------
st.sidebar.success("✅ Sesión activa")

perms = st.session_state.get("permisos", set())
plantel = st.session_state.get("plantel_usuario")

if "MENU_TODOS" in perms:
    st.sidebar.info(f"👤 {st.session_state.get('usuario')} (ADMIN)")
elif "MENU_SOLO_HISTORICO" in perms:
    st.sidebar.info(f"👤 {st.session_state.get('usuario')} (CAPACITA)")
elif plantel:
    st.sidebar.info(f"👤 {st.session_state.get('usuario')} (Plantel: {plantel})")
else:
    st.sidebar.info(f"👤 {st.session_state.get('usuario')}")

opciones = _menu_por_permisos(perms, plantel)
if not opciones:
    st.error("❌ Este usuario no tiene permisos de menú configurados en Datos1.xlsx.")
    st.stop()

opcion = st.sidebar.selectbox("📂 MENÚ PRINCIPAL", opciones)

if st.sidebar.button("🚪 Cerrar sesión"):
    for key in ["logueado", "usuario", "plantel_usuario", "permisos", "administrador"]:
        st.session_state.pop(key, None)
    st.rerun()

# ----------------------------
# Cargar Datos1.xlsx para todas las vistas excepto Histórico (histórico lo carga su view)
# ----------------------------
df, error = cargar_datos()
if error:
    st.error(f"❌ Error al cargar los datos: {error}")
    st.stop()

# ----------------------------
# Ruteo
# ----------------------------
if opcion == "Docentes y Módulos":
    vista_nc.mostrar(df, st.session_state.plantel_usuario, st.session_state.administrador)

elif opcion == "Estatal Docentes y Módulos":
    vista_estatal.mostrar_estatal(df)

elif opcion == "Docentes Seguimiento":
    vista_com.mostrar(df, st.session_state.plantel_usuario, st.session_state.administrador)

elif opcion == "Módulos Seguimiento":
    vista_mc.mostrar(df, st.session_state.plantel_usuario, st.session_state.administrador)

elif opcion == "Indicadores Académicos":
    mostrar_indicadores_academicos()

elif opcion == "Histórico de Indicadores":
    vista_hi.mostrar(st.session_state.plantel_usuario, st.session_state.administrador)

elif opcion == "Bitácora de Conexiones":
    vista_bc.mostrar()

elif opcion == "Captura Docentes":
    df_sc, error_sc = cargar_semcaptura()
    if error_sc:
        st.error(f"❌ Error al cargar SemCaptura: {error_sc}")
        st.stop()
    vista_cd.mostrar(df_sc, st.session_state.plantel_usuario, st.session_state.administrador)

elif opcion == "Ranking por docentes y módulos":
    mostrar_ranking_por_plantel(df, st.session_state.plantel_usuario)

# ✅ NUEVO
elif opcion == "Estudiantes por Grupo":
    mostrar_estudiantes_por_grupo()
