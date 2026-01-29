import streamlit as st
from data.validator import validar_usuario
from data.loader import cargar_datos, cargar_semcaptura
from data.logger import registrar_acceso

# Importar vistas
from views.indicadores_academicos import mostrar_indicadores_academicos
import views.no_competentes as vista_nc
import views.comportamiento as vista_com
import views.modulos_criticos as vista_mc
import views.mostrar_estatal as vista_estatal
import views.bitacora_conexiones as vista_bc
import views.captura_docentes as vista_cd
import views.historico_indicadores as vista_hi

# ✅ módulo
from views.estudiantes_por_grupo import mostrar_estudiantes_por_grupo

# ✅ Acceso Planteles
from views.acceso_planteles import mostrar_acceso_planteles


st.set_page_config(page_title="Tablero Docente", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stToolbar"] > div:nth-child(n+2) { display: none !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------
# Inicializar sesión
# ----------------------------
if "logueado" not in st.session_state:
    st.session_state.update(
        {
            "logueado": False,
            "usuario": None,
            "plantel_usuario": None,
            "permisos": set(),        # set[str]
            "administrador": False,   # scope GLOBAL si no tiene plantel
        }
    )


def _menu_por_permisos(perms: set[str], plantel: str | None) -> list[str]:
    """
    ✅ REGLA DE NEGOCIO:
    - Si hay permisos (perms no vacío): el menú se arma SOLO por permisos.
    - Si NO hay permisos: fallback por rol:
        * Plantel -> menú plantel (sin módulos globales)
        * GLOBAL  -> menú admin/global (incluye módulos globales)
    - Módulos "global_only" nunca aparecen a Plantel.
    - ✅ Se eliminó por completo la opción "Ranking ..."
    """

    perm_to_label = {
        "MENU_DOCENTES_MODULOS": "Docentes y Módulos",
        "MENU_ESTATAL_DOCENTES_MODULOS": "Estatal Docentes y Módulos",
        "MENU_DOCENTES_SEGUIMIENTO": "Docentes Seguimiento",
        "MENU_MODULOS_SEGUIMIENTO": "Módulos Seguimiento",
        "MENU_INDICADORES_ACADEMICOS": "Indicadores Académicos",
        "MENU_HISTORICO_INDICADORES": "Histórico de Indicadores",
        "MENU_CAPTURA_DOCENTES": "Captura Docentes",
        "MENU_BITACORA_CONEXIONES": "Bitácora de Conexiones",
        "MENU_ESTUDIANTES_POR_GRUPO": "Estudiantes por Grupo",

        # ✅ nuevo (controlado por permiso)
        "MENU_ACCESO_PLANTELES": "Acceso Planteles",
    }

    order = [
        "Docentes y Módulos",
        "Estatal Docentes y Módulos",
        "Docentes Seguimiento",
        "Módulos Seguimiento",
        "Indicadores Académicos",
        "Histórico de Indicadores",
        "Captura Docentes",
        "Bitácora de Conexiones",
        "Acceso Planteles",
        "Estudiantes por Grupo",
    ]

    global_only = {"Bitácora de Conexiones", "Estatal Docentes y Módulos", "Acceso Planteles"}
    allowed: set[str] = set()

    # ----------------------------
    # 1) SI HAY PERMISOS -> estricto por permisos
    # ----------------------------
    if perms:
        for code, label in perm_to_label.items():
            if code in perms:
                if plantel and label in global_only:
                    continue
                allowed.add(label)

        return [x for x in order if x in allowed]

    # ----------------------------
    # 2) NO HAY PERMISOS -> fallback por rol (controlado)
    # ----------------------------
    if plantel:
        allowed = {
            "Docentes y Módulos",
            "Docentes Seguimiento",
            "Módulos Seguimiento",
            "Indicadores Académicos",
            "Histórico de Indicadores",
            "Captura Docentes",
            "Estudiantes por Grupo",
        }
    else:
        allowed = {
            "Docentes y Módulos",
            "Estatal Docentes y Módulos",
            "Docentes Seguimiento",
            "Módulos Seguimiento",
            "Indicadores Académicos",
            "Histórico de Indicadores",
            "Captura Docentes",
            "Bitácora de Conexiones",
            "Acceso Planteles",
            "Estudiantes por Grupo",
        }

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
                is_admin_scope = plantel is None

                st.session_state.update(
                    {
                        "logueado": True,
                        "usuario": username,
                        "plantel_usuario": plantel,
                        "permisos": perms,
                        "administrador": is_admin_scope,
                    }
                )
                registrar_acceso(username, plantel)
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

if plantel:
    st.sidebar.info(f"👤 {st.session_state.get('usuario')} (Plantel: {plantel})")
else:
    st.sidebar.info(f"👤 {st.session_state.get('usuario')} (GLOBAL)")

opciones = _menu_por_permisos(perms, plantel)
if not opciones:
    st.error("❌ Este usuario no tiene opciones habilitadas. Revisa permisos/reglas en Datos1.xlsx.")
    st.stop()

opcion = st.sidebar.selectbox("📂 MENÚ PRINCIPAL", opciones)

if st.sidebar.button("🚪 Cerrar sesión"):
    for key in ["logueado", "usuario", "plantel_usuario", "permisos", "administrador"]:
        st.session_state.pop(key, None)
    st.rerun()

# ----------------------------
# Cargar Datos1.xlsx para vistas que lo requieren
# ----------------------------
df = None
error = None

# Acceso Planteles no necesita df de cargar_datos()
if opcion != "Acceso Planteles":
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

elif opcion == "Acceso Planteles":
    mostrar_acceso_planteles()

elif opcion == "Estudiantes por Grupo":
    mostrar_estudiantes_por_grupo()
