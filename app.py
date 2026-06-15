import streamlit as st
from data.validator import validar_usuario
from data.loader import cargar_datos, cargar_semcaptura, cargar_reprobacion
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

# Módulo estudiantes por grupo
from views.estudiantes_por_grupo import mostrar_estudiantes_por_grupo

# Acceso Planteles
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


# ==========================================================
# Configuración rol docente
# ==========================================================
# Recomendado: en tu archivo de usuarios/permisos agregar ROL_DOCENTE.
# Compatibilidad: si el campo plantel viene como "*NOMBRE DOCENTE",
# también se toma como rol docente.
ROL_DOCENTE_CODES = {
    "ROL_DOCENTE",
    "DOCENTE",
    "TIPO_DOCENTE",
    "USUARIO_DOCENTE",
}


def _normalizar_permisos(perms) -> set[str]:
    """
    Convierte permisos a set[str] aunque vengan como lista, tupla, None o texto.
    """
    if perms is None:
        return set()

    if isinstance(perms, set):
        return {str(p).strip() for p in perms if str(p).strip()}

    if isinstance(perms, (list, tuple)):
        return {str(p).strip() for p in perms if str(p).strip()}

    if isinstance(perms, str):
        raw = perms.replace("|", ",").replace(";", ",").split(",")
        return {p.strip() for p in raw if p.strip()}

    try:
        return {str(p).strip() for p in perms if str(p).strip()}
    except Exception:
        return set()


def _valor_parece_docente(valor) -> bool:
    """
    Detecta el caso actual donde validar_usuario devuelve en plantel
    el nombre del docente con prefijo '*'.
    Ejemplo: *ALVIRDE SALVADOR ARLINE GEORGINA
    """
    if valor is None:
        return False

    return str(valor).strip().startswith("*")


def _limpiar_nombre_docente(valor) -> str | None:
    """
    Limpia el nombre de docente cuando viene como '*NOMBRE'.
    """
    if valor is None:
        return None

    nombre = str(valor).strip()

    if nombre.startswith("*"):
        nombre = nombre[1:].strip()

    return nombre or None


def _es_rol_docente(perms: set[str], plantel_o_marca) -> bool:
    """
    Determina si el usuario pertenece al rol docente.
    """
    return bool(ROL_DOCENTE_CODES.intersection(perms)) or _valor_parece_docente(plantel_o_marca)


# ----------------------------
# Inicializar sesión
# ----------------------------
if "logueado" not in st.session_state:
    st.session_state.update(
        {
            "logueado": False,
            "usuario": None,
            "plantel_usuario": None,
            "permisos": set(),
            "administrador": False,
            "es_docente": False,
            "clave_docente": None,
            "nombre_docente_login": None,
        }
    )


def _menu_por_permisos(
    perms: set[str],
    plantel: str | None,
    es_docente: bool = False,
) -> list[str]:
    """
    REGLA DE NEGOCIO:
    - Si es docente: solo ve Docentes Seguimiento (FT).
    - Si hay permisos: el menú se arma SOLO por permisos.
    - Si no hay permisos: fallback por rol.
    - Los módulos global_only nunca aparecen a usuarios de plantel.
    """

    # ----------------------------
    # Nuevo rol docente
    # ----------------------------
    if es_docente:
        return ["Docentes Seguimiento (FT)"]

    perm_to_label = {
        "MENU_DOCENTES_MODULOS": "Top 15 Docentes y Módulos",
        "MENU_ESTATAL_DOCENTES_MODULOS": "Estatal Docentes y Módulos",
        "MENU_DOCENTES_SEGUIMIENTO": "Docentes Seguimiento (FT)",
        "MENU_MODULOS_SEGUIMIENTO": "Módulos Seguimiento (FT)",
        "MENU_INDICADORES_ACADEMICOS": "Indicadores Académicos",
        "MENU_HISTORICO_INDICADORES": "Histórico de Indicadores",
        "MENU_CAPTURA_DOCENTES": "Captura Docentes (FT)",
        "MENU_BITACORA_CONEXIONES": "Bitácora de Conexiones",
        "MENU_ESTUDIANTES_POR_GRUPO": "Estudiantes por Grupo",
        "MENU_ACCESO_PLANTELES": "Acceso Planteles",
    }

    order = [
        "Top 15 Docentes y Módulos",
        "Estatal Docentes y Módulos",
        "Docentes Seguimiento (FT)",
        "Módulos Seguimiento (FT)",
        "Captura Docentes (FT)",
        "Estudiantes por Grupo",
        "Indicadores Académicos",
        "Histórico de Indicadores",
        "Bitácora de Conexiones",
        "Acceso Planteles",
    ]

    global_only = {
        "Bitácora de Conexiones",
        "Estatal Docentes y Módulos",
        "Acceso Planteles",
    }

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
    # 2) NO HAY PERMISOS -> fallback por rol
    # ----------------------------
    if plantel:
        allowed = {
            "Top 15 Docentes y Módulos",
            "Docentes Seguimiento (FT)",
            "Módulos Seguimiento (FT)",
            "Captura Docentes (FT)",
            "Estudiantes por Grupo",
            "Indicadores Académicos",
            "Histórico de Indicadores",
        }
    else:
        allowed = {
            "Top 15 Docentes y Módulos",
            "Estatal Docentes y Módulos",
            "Docentes Seguimiento (FT)",
            "Módulos Seguimiento (FT)",
            "Captura Docentes (FT)",
            "Estudiantes por Grupo",
            "Indicadores Académicos",
            "Histórico de Indicadores",
            "Bitácora de Conexiones",
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
                perms = _normalizar_permisos(perms)

                # En tu caso actual, validar_usuario está devolviendo algo como:
                # plantel = "*ALVIRDE SALVADOR ARLINE GEORGINA"
                # Eso NO debe usarse como plantel, porque realmente es el nombre del docente.
                es_docente = _es_rol_docente(perms, plantel)

                clave_docente = str(username or usuario).strip() if es_docente else None
                nombre_docente_login = _limpiar_nombre_docente(plantel) if es_docente else None

                # Si es docente, plantel_usuario debe quedar en None.
                # El plantel real se obtiene después desde la hoja Datos,
                # una vez filtrado por clave_docente.
                plantel_usuario = None if es_docente else plantel

                # Si es docente, nunca es administrador aunque plantel_usuario sea None.
                is_admin_scope = (plantel_usuario is None) and not es_docente

                st.session_state.update(
                    {
                        "logueado": True,
                        "usuario": username,
                        "plantel_usuario": plantel_usuario,
                        "permisos": perms,
                        "administrador": is_admin_scope,
                        "es_docente": es_docente,
                        "clave_docente": clave_docente,
                        "nombre_docente_login": nombre_docente_login,
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
es_docente = st.session_state.get("es_docente", False)

if es_docente:
    nombre_docente = st.session_state.get("nombre_docente_login")
    clave_docente = st.session_state.get("clave_docente")

    if nombre_docente:
        st.sidebar.info(f"👨‍🏫 {clave_docente} (Docente: {nombre_docente})")
    else:
        st.sidebar.info(f"👨‍🏫 {clave_docente} (Docente)")
elif plantel:
    st.sidebar.info(f"👤 {st.session_state.get('usuario')} (Plantel: {plantel})")
else:
    st.sidebar.info(f"👤 {st.session_state.get('usuario')} (GLOBAL)")

opciones = _menu_por_permisos(perms, plantel, es_docente=es_docente)

if not opciones:
    st.error("❌ Este usuario no tiene opciones habilitadas. Revisa permisos/reglas en Datos1.xlsx.")
    st.stop()

opcion = st.sidebar.selectbox("📂 MENÚ PRINCIPAL", opciones)

if st.sidebar.button("🚪 Cerrar sesión"):
    for key in [
        "logueado",
        "usuario",
        "plantel_usuario",
        "permisos",
        "administrador",
        "es_docente",
        "clave_docente",
        "nombre_docente_login",
    ]:
        st.session_state.pop(key, None)

    st.rerun()


# ----------------------------
# Carga optimizada según vista
# ----------------------------
VISTAS_REQUIEREN_DATOS = {
    "Top 15 Docentes y Módulos",
    "Estatal Docentes y Módulos",
    "Docentes Seguimiento (FT)",
    "Módulos Seguimiento (FT)",
}

df = None

if opcion in VISTAS_REQUIEREN_DATOS:
    df, error = cargar_datos()

    if error:
        st.error(f"❌ Error al cargar los datos: {error}")
        st.stop()


# ----------------------------
# Ruteo
# ----------------------------
if opcion == "Top 15 Docentes y Módulos":
    vista_nc.mostrar(
        df,
        st.session_state.plantel_usuario,
        st.session_state.administrador,
    )

elif opcion == "Estatal Docentes y Módulos":
    vista_estatal.mostrar_estatal(df)

elif opcion == "Docentes Seguimiento (FT)":
    df_sc, error_sc = cargar_semcaptura()

    if error_sc:
        st.error(f"❌ Error al cargar SemCaptura: {error_sc}")
        st.stop()

    df_rep, error_rep = cargar_reprobacion()

    if error_rep:
        st.error(f"❌ Error al cargar Reprobacion: {error_rep}")
        st.stop()

    # IMPORTANTE:
    # Se usan parámetros nombrados para evitar que df_sc o df_rep
    # se pasen accidentalmente como es_docente o clave_docente_usuario.
    #
    # Si es docente, plantel_usuario se manda como None para NO filtrar por
    # el nombre del docente como si fuera plantel.
    vista_com.mostrar(
        df=df,
        plantel_usuario=None if st.session_state.get("es_docente", False) else st.session_state.get("plantel_usuario"),
        es_admin=False if st.session_state.get("es_docente", False) else st.session_state.get("administrador", False),
        es_docente=st.session_state.get("es_docente", False),
        clave_docente_usuario=st.session_state.get("clave_docente"),
        nombre_docente_usuario=st.session_state.get("nombre_docente_login"),
        semcaptura_raw=df_sc,
        reprobacion_raw=df_rep,
    )

elif opcion == "Módulos Seguimiento (FT)":
    df_sc, error_sc = cargar_semcaptura()

    if error_sc:
        st.error(f"❌ Error al cargar SemCaptura: {error_sc}")
        st.stop()

    vista_mc.mostrar(
        df,
        st.session_state.plantel_usuario,
        st.session_state.administrador,
        df_sc,
    )

elif opcion == "Indicadores Académicos":
    mostrar_indicadores_academicos()

elif opcion == "Histórico de Indicadores":
    vista_hi.mostrar(
        st.session_state.plantel_usuario,
        st.session_state.administrador,
    )

elif opcion == "Bitácora de Conexiones":
    vista_bc.mostrar()

elif opcion == "Captura Docentes (FT)":
    df_sc, error_sc = cargar_semcaptura()

    if error_sc:
        st.error(f"❌ Error al cargar SemCaptura: {error_sc}")
        st.stop()

    vista_cd.mostrar(
        df_sc,
        st.session_state.plantel_usuario,
        st.session_state.administrador,
    )

elif opcion == "Acceso Planteles":
    mostrar_acceso_planteles()

elif opcion == "Estudiantes por Grupo":
    mostrar_estudiantes_por_grupo()
