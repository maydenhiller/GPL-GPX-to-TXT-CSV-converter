import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import io
import zipfile
import struct

st.set_page_config(page_title="GPX/GPL Combiner", layout="centered")

st.title("📍 GPX / GPL Combiner")
st.write("Upload multiple `.gpx` or `.gpl` files (XML or binary) and combine them into `.csv` and `.txt` with reduced coordinates.")

uploaded_files = st.file_uploader(
    "Upload GPX or GPL files",
    type=["gpx", "gpl"],
    accept_multiple_files=True
)

def parse_binary_gpl(file_bytes, filename):
    """
    Parse binary DeLorme GPL format into a list of (lat, lon) tuples.
    This assumes the common format: 4-byte little-endian signed ints for lat/lon * 1e6.
    """
    coords = []
    try:
        # Skip header (first 256 bytes is common in DeLorme GPL)
        header_size = 256
        data = file_bytes[header_size:]
        record_size = 8  # 4 bytes lat + 4 bytes lon

        for i in range(0, len(data), record_size):
            chunk = data[i:i+record_size]
            if len(chunk) < record_size:
                break
            lat_raw, lon_raw = struct.unpack("<ii", chunk)
            lat = lat_raw / 1e6
            lon = lon_raw / 1e6
            coords.append((lat, lon))
    except Exception as e:
        st.error(f"{filename}: Error parsing binary GPL — {e}")
    return coords

def parse_gpx_or_gpl(file_bytes, filename):
    """
    Parses GPX or GPL XML and returns a list of (lat, lon) tuples.
    Detects binary GPL and routes to binary parser.
    """
    coords = []
    # Try to decode as text
    try:
        text = file_bytes.decode("utf-8-sig", errors="ignore").lstrip()
    except UnicodeDecodeError:
        text = ""

    # If not starting with '<', treat as binary GPL
    if not text.startswith("<"):
        st.info(f"{filename}: Detected binary GPL — decoding.")
        return parse_binary_gpl(file_bytes, filename)

    # Otherwise, parse as XML
    try:
        tree = ET.ElementTree(ET.fromstring(text))
        root = tree.getroot()

        # GPX tags
        for tag in [".//{*}trkpt", ".//{*}rtept"]:
            for pt in root.findall(tag):
                lat = pt.attrib.get("lat")
                lon = pt.attrib.get("lon")
                if lat and lon:
                    coords.append((float(lat), float(lon)))

        # GPL point tags
        for tag in [".//point", ".//{*}point"]:
            for pt in root.findall(tag):
                lat = pt.attrib.get("lat")
                lon = pt.attrib.get("lon")
                if lat and lon:
                    coords.append((float(lat), float(lon)))

        # Nested lat/lon elements
        if not coords:
            for pt in root.findall(".//point"):
                lat_el = pt.find("lat")
                lon_el = pt.find("lon")
                if lat_el is not None and lon_el is not None:
                    coords.append((float(lat_el.text), float(lon_el.text)))

    except ET.ParseError as e:
        st.error(f"{filename}: Error parsing XML — {e}")
    return coords

def reduce_coords(coords):
    """
    Keep first, last, and every other coordinate in between.
    """
    if len(coords) <= 2:
        return coords
    return [coords[0]] + coords[1:-1:2] + [coords[-1]]

if uploaded_files:
    all_lines = []
    txt_output = io.StringIO()
    log_info = []

    for file in uploaded_files:
        file_bytes = file.read()
        coords = parse_gpx_or_gpl(file_bytes, file.name)
        reduced = reduce_coords(coords)

        log_info.append(f"{file.name}: {len(coords)} → {len(reduced)} points")

        if reduced:
            all_lines.append(reduced)

    # Build TXT output
    for line in all_lines:
        txt_output.write("BEGIN LINE\n")
        for lat, lon in line:
            txt_output.write(f"{lat:.6f},{lon:.6f}\n")
        txt_output.write("END\n")

    # Build CSV output
    csv_rows = []
    for line in all_lines:
        for lat, lon in line:
            csv_rows.append({"lat": lat, "lon": lon})
    csv_df = pd.DataFrame(csv_rows)

    # Prepare downloads
    txt_bytes = txt_output.getvalue().encode("utf-8")
    csv_bytes = csv_df.to_csv(index=False).encode("utf-8")

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

    st.subheader("Processing Log")
    for entry in log_info:
        st.write(entry)
