import streamlit as st

# --- CONFIGURACIÓN DE PÁGINA (Debe ir primero) ---
st.set_page_config(layout="wide", page_title="Dashboard de Competencias Académicas", page_icon="📊")

# --- IMPORTACIONES ---
from data.validator import validar_usuario
from data.logger import registrar_acceso, contar_accesos

# --- INICIALIZACIÓN DE VARIABLES DE SESIÓN ---
if "logueado" not in st.session_state:
    st.session_state.update({
        "logueado": False,
        "plantel_usuario": None,
        "administrador": False
    })

# --- FORMULARIO DE LOGEO ---
if not st.session_state.logueado:
    st.sidebar.title("🔒 Inicio de sesión")
    usuario = st.sidebar.text_input("👤 Usuario", key="login_usuario")
    contrasena = st.sidebar.text_input("🔑 Contraseña", type="password", key="login_contrasena")

    if st.sidebar.button("Iniciar sesión"):
        ok, plantel, es_admin = validar_usuario(usuario, contrasena)
        if ok:
            registrar_acceso(usuario)
            st.session_state.update({
                "logueado": True,
                "plantel_usuario": plantel,
                "administrador": es_admin
            })
            st.rerun()
        else:
            st.sidebar.error("Acceso denegado. Verifica tus credenciales.")