import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import io
import zipfile
import struct
import binascii

st.set_page_config(page_title="GPX/GPL Combiner", layout="centered")

st.title("📍 GPX / GPL Combiner (Debug Mode)")
st.write("Upload `.gpx` or `.gpl` files — will parse XML or binary GPL, and show raw binary debug for GPLs.")

uploaded_files = st.file_uploader(
    "Upload GPX or GPL files",
    type=["gpx", "gpl"],
    accept_multiple_files=True
)

def debug_binary_gpl(file_bytes, filename):
    """
    Show first few records in raw hex and int/double interpretations.
    """
    st.subheader(f"Binary GPL Debug: {filename}")
    header_size = 256
    data = file_bytes[header_size:]
    record_size = 8  # initial guess: 4 bytes lat + 4 bytes lon
    for i in range(0, min(len(data), record_size*5), record_size):
        chunk = data[i:i+record_size]
        hex_str = binascii.hexlify(chunk).decode("ascii")
        try:
            ints = struct.unpack("<ii", chunk)
        except struct.error:
            ints = ("?", "?")
        try:
            floats = struct.unpack("<ff", chunk)
        except struct.error:
            floats = ("?", "?")
        try:
            doubles = struct.unpack("<dd", chunk + b"\x00"*(16-len(chunk))) if len(chunk) >= 16 else ("?", "?")
        except struct.error:
            doubles = ("?", "?")
        st.write(f"Record {i//record_size+1}: HEX={hex_str} int32={ints} float32={floats} float64={doubles}")

def parse_binary_gpl(file_bytes, filename):
    """
    Parse binary GPL with current guess: int32 little-endian scaled by 1e6.
    """
    coords = []
    header_size = 256
    data = file_bytes[header_size:]
    record_size = 8
    for i in range(0, len(data), record_size):
        chunk = data[i:i+record_size]
        if len(chunk) < record_size:
            break
        lat_raw, lon_raw = struct.unpack("<ii", chunk)
        lat = lat_raw / 1e6
        lon = lon_raw / 1e6
        coords.append((lat, lon))
    return coords

def parse_gpx_or_gpl(file_bytes, filename):
    coords = []
    try:
        text = file_bytes.decode("utf-8-sig", errors="ignore").lstrip()
    except UnicodeDecodeError:
        text = ""

    if not text.startswith("<"):
        st.info(f"{filename}: Detected binary GPL — decoding.")
        debug_binary_gpl(file_bytes, filename)
        return parse_binary_gpl(file_bytes, filename)

    try:
        tree = ET.ElementTree(ET.fromstring(text))
        root = tree.getroot()
        for tag in [".//{*}trkpt", ".//{*}rtept"]:
            for pt in root.findall(tag):
                lat = pt.attrib.get("lat")
                lon = pt.attrib.get("lon")
                if lat and lon:
                    coords.append((float(lat), float(lon)))
        for tag in [".//point", ".//{*}point"]:
            for pt in root.findall(tag):
                lat = pt.attrib.get("lat")
                lon = pt.attrib.get("lon")
                if lat and lon:
                    coords.append((float(lat), float(lon)))
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

    for line in all_lines:
        txt_output.write("BEGIN LINE\n")
        for lat, lon in line:
            txt_output.write(f"{lat:.6f},{lon:.6f}\n")
        txt_output.write("END\n")

    csv_rows = []
    for line in all_lines:
        for lat, lon in line:
            csv_rows.append({"lat": lat, "lon": lon})
    csv_df = pd.DataFrame(csv_rows)

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
