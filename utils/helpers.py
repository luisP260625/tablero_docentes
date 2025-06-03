import io
import pandas as pd

def to_excel(df_pandas):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_pandas.to_excel(writer, index=False)
    return output.getvalue()

