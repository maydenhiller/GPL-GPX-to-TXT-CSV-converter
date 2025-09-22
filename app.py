import io
import struct
from typing import List, Tuple

import pandas as pd
import streamlit as st
import xml.etree.ElementTree as ET


st.set_page_config(page_title="GPX/GPL Combiner", layout="centered")

st.title("📍 GPX / GPL Combiner")
st.write("Upload multiple `.gpx` or `.gpl` files (XML or binary). The app will combine them into `.csv` and `.txt` and reduce points by keeping the first and last point, skipping every other point in between.")

uploaded_files = st.file_uploader(
    "Upload GPX or GPL files",
    type=["gpx", "gpl"],
    accept_multiple_files=True,
    help="You can drag and drop multiple files here (up to 200 MB each)."
)

# --------------------------
# Helpers
# --------------------------

def is_valid_lat_lon(lat: float, lon: float) -> bool:
    return (-90.0 <= lat <= 90.0) and (-180.0 <= lon <= 180.0)

def normalize_pair(lat: float, lon: float):
    """
    Try to coerce a candidate pair into a valid lat, lon:
    - If in range, return as is
    - If swapped gives valid, swap
    - If dividing by 100 fixes either (to catch 3229.33 -> 32.2933), try variants
    Return (lat, lon) if valid, else None.
    """
    candidates = []

    # As-is
    candidates.append((lat, lon))
    # Swapped
    candidates.append((lon, lat))

    # Scale by 100 if obviously too large for degrees (heuristic)
    if abs(lat) > 180 or abs(lon) > 180:
        candidates.append((lat / 100.0, lon / 100.0))
        candidates.append((lon / 100.0, lat / 100.0))

    # Scale by 1000 (extreme fallback if needed)
    if abs(lat) > 1000 or abs(lon) > 1000:
        candidates.append((lat / 1000.0, lon / 1000.0))
        candidates.append((lon / 1000.0, lat / 1000.0))

    for a, b in candidates:
        if is_valid_lat_lon(a, b):
            return a, b
    return None

def reduce_coords(coords: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """
    Keep first, last, and every other coordinate in between.
    """
    if len(coords) <= 2:
        return coords
    return [coords[0]] + coords[1:-1:2] + [coords[-1]]

def dedupe_consecutive(coords: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """
    Remove exact consecutive duplicates to avoid repeated points bloating output.
    """
    if not coords:
        return coords
    out = [coords[0]]
    for lat, lon in coords[1:]:
        if (lat, lon) != out[-1]:
            out.append((lat, lon))
    return out

# --------------------------
# Parsing: XML GPX/GPL
# --------------------------

def parse_gpx_or_gpl_xml(file_bytes: bytes, filename: str) -> List[Tuple[float, float]]]:
    coords = []
    # Decode text safely, stripping BOM/whitespace
    text = file_bytes.decode("utf-8-sig", errors="ignore").lstrip()
    if not text.startswith("<"):
        return coords  # not XML

    try:
        tree = ET.ElementTree(ET.fromstring(text))
        root = tree.getroot()

        # GPX tracks and routes
        for tag in [".//{*}trkpt", ".//{*}rtept"]:
            for pt in root.findall(tag):
                lat = pt.attrib.get("lat")
                lon = pt.attrib.get("lon")
                if lat and lon:
                    latf, lonf = float(lat), float(lon)
                    if is_valid_lat_lon(latf, lonf):
                        coords.append((latf, lonf))

        # GPL point elements (either attributes or nested)
        for tag in [".//point", ".//{*}point"]:
            for pt in root.findall(tag):
                lat = pt.attrib.get("lat")
                lon = pt.attrib.get("lon")
                if lat and lon:
                    latf, lonf = float(lat), float(lon)
                    if is_valid_lat_lon(latf, lonf):
                        coords.append((latf, lonf))
                else:
                    lat_el = pt.find("lat")
                    lon_el = pt.find("lon")
                    if lat_el is not None and lon_el is not None:
                        latf, lonf = float(lat_el.text), float(lon_el.text)
                        if is_valid_lat_lon(latf, lonf):
                            coords.append((latf, lonf))

    except ET.ParseError as e:
        st.error(f"{filename}: XML parse error — {e}")
    return coords

# --------------------------
# Parsing: Binary GPL (robust heuristic)
# --------------------------

def parse_gpl_binary(file_bytes: bytes, filename: str) -> Tuple[List[Tuple[float, float]], dict]:
    """
    Heuristic binary GPL parser that:
    - Skips a 256-byte header (common)
    - Reads in 32-byte records (observed in your sample)
    - For each 32-byte chunk, tries multiple 16-byte windows (offsets 0, 8, 16)
      as pairs of little-endian float64 (dd).
    - If those fail, tries float32 pairs (ff) at offsets (0, 8) to build a candidate.
    - Applies normalization to coerce plausible lat/lon (swap/scale if needed).
    - Accepts the first plausible pair per chunk.
    - Returns decoded coords and a stats dict for logs.
    """
    header_size = 256
    data = file_bytes[header_size:]
    stride = 32  # based on your deep debug, where good pairs appeared consistently
    decoded = []
    total_chunks = 0
    used64 = 0
    used32 = 0
    scaled = 0
    swapped = 0
    skipped = 0

    for i in range(0, len(data), stride):
        total_chunks += 1
        chunk = data[i:i+stride]
        if len(chunk) < 8:
            skipped += 1
            continue

        chosen = None

        # Try float64 pairs from aligned 16-byte windows
        for off in (0, 8, 16):
            if off + 16 <= len(chunk):
                try:
                    a, b = struct.unpack("<dd", chunk[off:off+16])
                    norm = normalize_pair(a, b)
                    if norm is not None:
                        chosen = norm
                        used64 += 1
                        # Track if normalization implied swap/scale
                        if (a, b) != norm and (b, a) == norm:
                            swapped += 1
                        if abs(a) > 180 or abs(b) > 180:
                            scaled += 1
                        break
                except struct.error:
                    pass
        # If not found, try float32 from first 8 bytes (two 4-byte floats)
        if chosen is None and len(chunk) >= 8:
            try:
                a32, b32 = struct.unpack("<ff", chunk[:8])
                norm = normalize_pair(float(a32), float(b32))
                if norm is not None:
                    chosen = norm
                    used32 += 1
                    if (a32, b32) != norm and (b32, a32) == norm:
                        swapped += 1
                    if abs(a32) > 180 or abs(b32) > 180:
                        scaled += 1
            except struct.error:
                pass

        if chosen is not None:
            decoded.append(chosen)
        else:
            skipped += 1

    decoded = dedupe_consecutive(decoded)
    stats = {
        "chunks": total_chunks,
        "decoded": len(decoded),
        "used64": used64,
        "used32": used32,
        "scaled": scaled,
        "swapped": swapped,
        "skipped": skipped
    }
    return decoded, stats

def parse_any(file_bytes: bytes, filename: str) -> Tuple[List[Tuple[float, float]], dict]:
    """
    Route to XML or binary parser. Returns coords and a stats dict.
    """
    # Try XML first
    try:
        text = file_bytes.decode("utf-8-sig", errors="ignore").lstrip()
    except UnicodeDecodeError:
        text = ""

    if text.startswith("<"):
        coords = parse_gpx_or_gpl_xml(file_bytes, filename)
        return coords, {
            "type": "xml",
            "decoded": len(coords),
            "skipped": 0,
            "note": "XML parsed"
        }
    else:
        st.info(f"{filename}: Detected binary GPL — decoding with robust heuristic.")
        coords, stats = parse_gpl_binary(file_bytes, filename)
        stats["type"] = "binary"
        return coords, stats

# --------------------------
# Main flow
# --------------------------

if uploaded_files:
    all_lines: List[List[Tuple[float, float]]] = []
    logs = []

    for file in uploaded_files:
        file_bytes = file.read()
        coords, stats = parse_any(file_bytes, file.name)
        reduced = reduce_coords(coords)
        all_lines.append(reduced)

        logs.append({
            "file": file.name,
            "type": stats.get("type", "?"),
            "decoded_points": stats.get("decoded", 0),
            "reduced_points": len(reduced),
            "skipped_records": stats.get("skipped", 0),
            "used64": stats.get("used64", 0) if stats.get("type") == "binary" else None,
            "used32": stats.get("used32", 0) if stats.get("type") == "binary" else None,
            "scaled": stats.get("scaled", 0) if stats.get("type") == "binary" else None,
            "swapped": stats.get("swapped", 0) if stats.get("type") == "binary" else None,
            "note": stats.get("note", "")
        })

    # Build TXT output with required formatting
    txt_io = io.StringIO()
    for line in all_lines:
        txt_io.write("BEGIN LINE\n")
        for lat, lon in line:
            txt_io.write(f"{lat:.6f},{lon:.6f}\n")
        txt_io.write("END\n")
    txt_bytes = txt_io.getvalue().encode("utf-8")

    # Build CSV output
    csv_rows = []
    for line in all_lines:
        for lat, lon in line:
            csv_rows.append({"lat": lat, "lon": lon})
    csv_df = pd.DataFrame(csv_rows)
    csv_bytes = csv_df.to_csv(index=False).encode("utf-8")

    # Zip both files
    zip_buf = io.BytesIO()
    import zipfile
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("combined.txt", txt_bytes)
        zf.writestr("combined.csv", csv_bytes)
    zip_buf.seek(0)

    st.success("✅ Files processed successfully!")
    st.download_button(
        "⬇️ Download combined.zip",
        data=zip_buf,
        file_name="combined.zip",
        mime="application/zip"
    )

    # Show processing log
    st.subheader("Processing log")
    for entry in logs:
        parts = [
            f"- File: {entry['file']}",
            f"Type: {entry['type']}",
            f"Decoded: {entry['decoded_points']}",
            f"Reduced: {entry['reduced_points']}",
            f"Skipped: {entry['skipped_records']}"
        ]
        if entry["type"] == "binary":
            parts.extend([
                f"used64: {entry['used64']}",
                f"used32: {entry['used32']}",
                f"scaled: {entry['scaled']}",
                f"swapped: {entry['swapped']}"
            ])
        if entry.get("note"):
            parts.append(f"Note: {entry['note']}")
        st.write("  ".join(parts))
