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

st.markdown(
    """
    <style>
    [data-testid="stToolbar"] > div:nth-child(n+2) {
        display: none !important;
    }
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
            # ✅ aquí SIEMPRE guardamos CLAVES (strings) ej. MENU_DOCENTES_MODULOS
            "permisos": set(),
            # compatibilidad con vistas actuales: admin = puede ver todo (scope)
            "administrador": False,
        }
    )


def _menu_por_permisos(perms: set[str], plantel: str | None) -> list[str]:
    """
    Reglas:
    - El Excel asigna permisos por IDs, pero validator.py ya devuelve CLAVES (ej. MENU_DOCENTES_MODULOS)
    - Plantel: ve todo FILTRADO por su plantel (scope), pero el menú se controla por permisos.
      * Además, se muestra "Ranking por docentes y módulos" como opción base para plantel.
      * Plantel NO verá módulos "globales" aunque se les asigne por error (Bitácora / Estatal).
    - Admin/Otros (sin plantel): menú por permisos, alcance global.

    Permisos esperados (hoja Permisos):
      MENU_DOCENTES_MODULOS
      MENU_ESTATAL_DOCENTES_MODULOS
      MENU_DOCENTES_SEGUIMIENTO
      MENU_MODULOS_SEGUIMIENTO
      MENU_INDICADORES_ACADEMICOS
      MENU_HISTORICO_INDICADORES
      MENU_CAPTURA_DOCENTES
      MENU_BITACORA_CONEXIONES
      MENU_ESTUDIANTES_POR_GRUPO
    """

    # Mapeo: clave -> etiqueta del menú
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
    }

    # Orden final (para que el selectbox se vea siempre igual)
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
        "Estudiantes por Grupo",
    ]

    allowed: set[str] = set()

    # ✅ Plantel: opción base (no depende de permisos)
    if plantel:
        allowed.add("Ranking por docentes y módulos")

    # ✅ Permisos por clave
    for code, label in perm_to_label.items():
        if code in perms:
            # módulos globales: ocultarlos a plantel aunque se asignen por error
            if plantel and label in {"Bitácora de Conexiones", "Estatal Docentes y Módulos"}:
                continue
            allowed.add(label)

    # ✅ Fallback práctico: si no hay permisos pero sí plantel, no dejarlo sin menú
    if plantel and allowed == {"Ranking por docentes y módulos"}:
        # Menú plantel “default” (como estaba tu app)
        allowed.update(
            {
                "Docentes y Módulos",
                "Docentes Seguimiento",
                "Módulos Seguimiento",
                "Indicadores Académicos",
                "Histórico de Indicadores",
                "Captura Docentes",
                "Estudiantes por Grupo",
            }
        )

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
                # ✅ Alcance (scope): si no tiene plantel, se considera usuario global (admin/u otro)
                is_admin_scope = plantel is None

                st.session_state.update(
                    {
                        "logueado": True,
                        "usuario": username,
                        "plantel_usuario": plantel,
                        "permisos": perms,  # set[str] de claves
                        "administrador": is_admin_scope,
                    }
                )
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
is_admin_scope = bool(st.session_state.get("administrador"))

if plantel:
    st.sidebar.info(f"👤 {st.session_state.get('usuario')} (Plantel: {plantel})")
else:
    st.sidebar.info(f"👤 {st.session_state.get('usuario')} (GLOBAL)")

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

elif opcion == "Estudiantes por Grupo":
    mostrar_estudiantes_por_grupo()
