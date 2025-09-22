import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import io
import zipfile
import os

st.set_page_config(page_title="GPX/GPL Combiner", layout="centered")

st.title("📍 GPX / GPL Combiner")
st.write("Upload multiple `.gpx` or `.gpl` files and combine them into `.csv` and `.txt` with reduced coordinates.")

uploaded_files = st.file_uploader(
    "Upload GPX or GPL files",
    type=["gpx", "gpl"],
    accept_multiple_files=True
)

def parse_gpx_or_gpl(file_bytes):
    """
    Parses GPX or GPL XML and returns a list of (lat, lon) tuples.
    """
    coords = []
    try:
        tree = ET.parse(io.BytesIO(file_bytes))
        root = tree.getroot()

        # GPX: look for trkpt
        for trkpt in root.findall(".//{*}trkpt"):
            lat = trkpt.attrib.get("lat")
            lon = trkpt.attrib.get("lon")
            if lat and lon:
                coords.append((float(lat), float(lon)))

        # GPL: look for point elements (DeLorme format)
        for pt in root.findall(".//point"):
            lat = pt.attrib.get("lat")
            lon = pt.attrib.get("lon")
            if lat and lon:
                coords.append((float(lat), float(lon)))

    except ET.ParseError:
        st.error("Error parsing file. Ensure it's valid GPX or GPL.")
    return coords

def reduce_coords(coords):
    """
    Keep first, last, and every other coordinate in between.
    """
    if len(coords) <= 2:
        return coords
    reduced = [coords[0]] + coords[1:-1:2] + [coords[-1]]
    return reduced

if uploaded_files:
    all_lines = []
    txt_output = io.StringIO()

    for file in uploaded_files:
        coords = parse_gpx_or_gpl(file.read())
        coords = reduce_coords(coords)

        if coords:
            all_lines.append(coords)

    # Build TXT output
    for line in all_lines:
        txt_output.write("BEGIN LINE\n")
        for lat, lon in line:
            txt_output.write(f"{lat:.6f},{lon:.6f}\n")
        txt_output.write("END\n")

    # Build CSV output (flattened)
    csv_rows = []
    for line in all_lines:
        for lat, lon in line:
            csv_rows.append({"lat": lat, "lon": lon})
    csv_df = pd.DataFrame(csv_rows)

    # Prepare downloads
    txt_bytes = txt_output.getvalue().encode("utf-8")
    csv_bytes = csv_df.to_csv(index=False).encode("utf-8")

    # Zip both files for download
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("combined.txt", txt_bytes)
        zf.writestr("combined.csv", csv_bytes)
    zip_buffer.seek(0)

    st.success("✅ Files processed successfully!")
    st.download_button(
        label="⬇️ Download combined.zip",
        data=zip_buffer,
        file_name="combined.zip",
        mime="application/zip"
    )
