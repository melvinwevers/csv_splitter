import streamlit as st
import pandas as pd
import zipfile
import io

st.set_page_config(page_title="CSV/TSV Splitter", page_icon="📄")

st.title("CSV/TSV Splitter")
st.write("Upload a CSV or TSV file and split the OCR column into separate text files.")

uploaded_file = st.file_uploader("Upload your CSV/TSV file", type=["csv", "tsv"])

if uploaded_file is not None:
    # Detect separator based on file extension
    if uploaded_file.name.endswith('.tsv'):
        df = pd.read_csv(uploaded_file, sep='\t')
    else:
        df = pd.read_csv(uploaded_file)

    st.write(f"**Loaded {len(df)} rows**")
    st.dataframe(df.head())

    # Check required columns
    if 'ocr' not in df.columns:
        st.error("The file must contain an 'ocr' column.")
    elif 'date' not in df.columns:
        st.error("The file must contain a 'date' column.")
    else:
        # Parse date column
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df['year'] = df['date'].dt.year
        df['month'] = df['date'].dt.to_period('M').astype(str)

        split_option = st.selectbox(
            "Split by:",
            ["Per Row", "Per Month", "Per Year", "Per Newspaper", "Per Spatial"]
        )

        if st.button("Generate ZIP"):
            zip_buffer = io.BytesIO()

            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                if split_option == "Per Row":
                    # Group by date and add counter for duplicates
                    date_counts = {}
                    for _, row in df.iterrows():
                        if pd.notna(row['date']):
                            date_str = row['date'].strftime('%Y-%m-%d')
                        else:
                            date_str = 'unknown'
                        date_counts[date_str] = date_counts.get(date_str, 0) + 1
                        count = date_counts[date_str]
                        if count == 1:
                            filename = f"{date_str}.txt"
                        else:
                            filename = f"{date_str}_{count}.txt"
                        content = str(row['ocr']) if pd.notna(row['ocr']) else ""
                        zf.writestr(filename, content)

                elif split_option == "Per Month":
                    for month, group in df.groupby('month'):
                        filename = f"{month}.txt"
                        content = "\n\n---\n\n".join(
                            str(row['ocr']) if pd.notna(row['ocr']) else ""
                            for _, row in group.iterrows()
                        )
                        zf.writestr(filename, content)

                elif split_option == "Per Year":
                    for year, group in df.groupby('year'):
                        filename = f"{int(year)}.txt"
                        content = "\n\n---\n\n".join(
                            str(row['ocr']) if pd.notna(row['ocr']) else ""
                            for _, row in group.iterrows()
                        )
                        zf.writestr(filename, content)

                elif split_option == "Per Newspaper":
                    if 'newspaper' not in df.columns:
                        st.error(
                            "The file must contain a 'newspaper' column "
                            "for this option."
                        )
                    else:
                        for newspaper, group in df.groupby('newspaper'):
                            # Sanitize filename
                            safe_name = "".join(
                                c if c.isalnum() or c in (' ', '-', '_') else '_'
                                for c in str(newspaper)
                            )
                            filename = f"{safe_name}.txt"
                            content = "\n\n---\n\n".join(
                                str(row['ocr']) if pd.notna(row['ocr']) else ""
                                for _, row in group.iterrows()
                            )
                            zf.writestr(filename, content)

                elif split_option == "Per Spatial":
                    if 'spatial' not in df.columns:
                        st.error(
                            "The file must contain a 'spatial' column "
                            "for this option."
                        )
                    else:
                        for spatial, group in df.groupby('spatial'):
                            # Sanitize filename
                            safe_name = "".join(
                                c if c.isalnum() or c in (' ', '-', '_') else '_'
                                for c in str(spatial)
                            )
                            filename = f"{safe_name}.txt"
                            content = "\n\n---\n\n".join(
                                str(row['ocr']) if pd.notna(row['ocr']) else ""
                                for _, row in group.iterrows()
                            )
                            zf.writestr(filename, content)

            zip_buffer.seek(0)

            st.download_button(
                label="Download ZIP",
                data=zip_buffer,
                file_name=f"ocr_split_{split_option.lower().replace(' ', '_')}.zip",
                mime="application/zip"
            )
