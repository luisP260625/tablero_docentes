import streamlit as st

# Inicializar sesión si no existe
if "logueado" not in st.session_state:
    st.session_state.logueado = False

# Mostrar formulario de login si no está logueado
if not st.session_state.logueado:
    st.title("🔐 Inicio de sesión")

    usuario = st.text_input("Usuario")
    contrasena = st.text_input("Contraseña", type="password")

    if st.button("Iniciar sesión"):
        if usuario == "admin" and contrasena == "1234":
            st.session_state.logueado = True
            st.success("✅ ¡Sesión iniciada correctamente!")
            st.rerun()
        else:
            st.error("❌ Credenciales incorrectas")
else:
    st.success("✅ Ya estás logueado")
    if st.button("Cerrar sesión"):
        st.session_state.logueado = False
        st.rerun()
