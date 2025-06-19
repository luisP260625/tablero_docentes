import streamlit as st
from data.validator import validar_usuario

# Inicializar sesión
if "logueado" not in st.session_state:
    st.session_state.update({
        "logueado": False,
        "plantel_usuario": None,
        "administrador": False
    })

# LOGIN
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
            st.success("✅ ¡Sesión iniciada!")
            st.rerun()
        else:
            st.error("❌ Credenciales incorrectas")
    st.stop()

# SESIÓN ACTIVA
st.sidebar.success("✅ Sesión activa")
st.sidebar.info(f"👤 {'Administrador' if st.session_state.administrador else f'Plantel: {st.session_state.plantel_usuario}'}")

if st.sidebar.button("Cerrar sesión"):
    for key in ["logueado", "plantel_usuario", "administrador"]:
        st.session_state.pop(key, None)
    st.rerun()

# MENÚ SEGÚN ROL
if st.session_state.administrador:
    opcion = st.sidebar.radio("Menú administrador", ["Estatal", "Bitácora", "Configuraciones"])
    st.write(f"🔧 Vista seleccionada: {opcion}")
else:
    opcion = st.sidebar.radio("Menú plantel", ["Ranking", "No competentes", "Comportamiento", "Críticos"])
    st.write(f"🏫 Vista seleccionada: {opcion} del plantel {st.session_state.plantel_usuario}")

