import io
import struct
from typing import List, Tuple
import pandas as pd
import streamlit as st
import xml.etree.ElementTree as ET
import zipfile

st.set_page_config(page_title="GPL-GPX-to-TXT-CSV-converter", layout="centered")
st.title("GPL-GPX-to-TXT-CSV-converter")
st.write("Upload `.gpx` or `.gpl` files (XML or binary). Binary GPLs are decoded with adaptive offset scanning and U.S. filtering.")

uploaded_files = st.file_uploader(
    "Upload GPX or GPL files",
    type=["gpx", "gpl"],
    accept_multiple_files=True
)

def is_valid_us_lat_lon(lat: float, lon: float) -> bool:
    return (24.5 <= lat <= 49.5) and (-125.0 <= lon <= -66.5)

def dedupe_consecutive(coords: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    if not coords:
        return coords
    out = [coords[0]]
    for lat, lon in coords[1:]:
        if (lat, lon) != out[-1]:
            out.append((lat, lon))
    return out

def reduce_coords(coords: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    if len(coords) <= 2:
        return coords
    return [coords[0]] + coords[1:-1:2] + [coords[-1]]

def parse_gpx_or_gpl_xml(file_bytes: bytes, filename: str) -> List[Tuple[float, float]]:
    coords = []
    try:
        text = file_bytes.decode("utf-8-sig", errors="ignore").lstrip()
    except UnicodeDecodeError:
        return coords
    if not text.startswith("<"):
        return coords
    try:
        tree = ET.ElementTree(ET.fromstring(text))
        root = tree.getroot()
        for tag in [".//{*}trkpt", ".//{*}rtept"]:
            for pt in root.findall(tag):
                lat = pt.attrib.get("lat")
                lon = pt.attrib.get("lon")
                if lat and lon:
                    latf, lonf = float(lat), float(lon)
                    if is_valid_us_lat_lon(latf, lonf):
                        coords.append((latf, lonf))
        for tag in [".//point", ".//{*}point"]:
            for pt in root.findall(tag):
                lat = pt.attrib.get("lat")
                lon = pt.attrib.get("lon")
                if lat and lon:
                    latf, lonf = float(lat), float(lon)
                    if is_valid_us_lat_lon(latf, lonf):
                        coords.append((latf, lonf))
                else:
                    lat_el = pt.find("lat")
                    lon_el = pt.find("lon")
                    if lat_el is not None and lon_el is not None:
                        latf, lonf = float(lat_el.text), float(lon_el.text)
                        if is_valid_us_lat_lon(latf, lonf):
                            coords.append((latf, lonf))
    except ET.ParseError as e:
        st.error(f"{filename}: XML parse error — {e}")
    return coords

def parse_gpl_binary_adaptive(file_bytes: bytes, filename: str) -> List[Tuple[float, float]]:
    coords = []
    header_size = 256
    data = file_bytes[header_size:]
    stride = 32

    for i in range(0, len(data), stride):
        chunk = data[i:i+stride]
        if len(chunk) < 16:
            continue

        for offset in [0, 8, 16]:
            try:
                lat, lon = struct.unpack("<dd", chunk[offset:offset+16])
                if is_valid_us_lat_lon(lat, lon):
                    coords.append((lat, lon))
            except struct.error:
                continue

    return dedupe_consecutive(coords)

def parse_any(file_bytes: bytes, filename: str) -> List[Tuple[float, float]]:
    try:
        text = file_bytes.decode("utf-8-sig", errors="ignore").lstrip()
    except UnicodeDecodeError:
        text = ""
    if text.startswith("<"):
        return parse_gpx_or_gpl_xml(file_bytes, filename)
    else:
        st.info(f"{filename}: Detected binary GPL — decoding with adaptive offset scanning.")
        return parse_gpl_binary_adaptive(file_bytes, filename)

if uploaded_files:
    all_lines = []
    logs = []
    for file in uploaded_files:
        file_bytes = file.read()
        coords = parse_any(file_bytes, file.name)
        reduced = reduce_coords(coords)
        all_lines.append(reduced)
        logs.append(f"{file.name}: {len(coords)} → {len(reduced)} points")

    txt_io = io.StringIO()
    txt_io.write("Latitude,Longitude\n")
    for line in all_lines:
        txt_io.write("BEGIN LINE\n")
        for lat, lon in line:
            txt_io.write(f"{lat:.6f},{lon:.6f}\n")
        txt_io.write("END\n")
    txt_bytes = txt_io.getvalue().encode("utf-8")

    # CSV with renamed columns
    csv_rows = []
    for idx, line in enumerate(all_lines):
        for lat, lon in line:
            csv_rows.append({
                "Latitude": f"{lat:.6f}",
                "Longitude": f"{lon:.6f}",
                "icon": "None",
                "LineStringColor": "Blue"
            })
        if idx < len(all_lines) - 1:
            csv_rows.append({
                "Latitude": "",
                "Longitude": "",
                "icon": "",
                "LineStringColor": ""
            })
    csv_df = pd.DataFrame(csv_rows)
    csv_bytes = csv_df.to_csv(index=False).encode("utf-8")

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("Combined Access Files.txt", txt_bytes)
        zf.writestr("Combined Access Files.csv", csv_bytes)
    zip_buf.seek(0)

    st.success("✅ Files processed successfully!")
    st.download_button(
        "⬇️ Download Combined Access Files.zip",
        data=zip_buf,
        file_name="Combined Access Files.zip",
        mime="application/zip"
    )

    st.subheader("Processing log")
    for entry in logs:
        st.write(entry)
