import matplotlib.pyplot as plt
import streamlit as st

def graficar_barras(df_plot, etiqueta, color="crimson"):
    fig, ax = plt.subplots(figsize=(10, max(4, len(df_plot)*0.5)))
    bars = ax.barh(df_plot[etiqueta], df_plot["NO_COMP"], color=color)
    ax.invert_yaxis()
    for bar, nc, total in zip(bars, df_plot["NO_COMP"], df_plot["TOTAL"]):
        pct = (nc / total) * 100 if total > 0 else 0
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2, f"{nc} - {pct:.1f}%",
                ha='left', va='center', fontsize=9, color="black", fontweight="bold")
    ax.set_xlabel("Alumnos No Competentes")
    st.pyplot(fig)

