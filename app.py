import streamlit as st
import struct
import binascii

st.set_page_config(page_title="GPL Binary Comparator", layout="wide")
st.title("🧪 GPL Binary Comparator")
st.write("Upload two `.gpl` files to compare their binary structure and coordinate decoding.")

uploaded_files = st.file_uploader(
    "Upload exactly two GPL files",
    type=["gpl"],
    accept_multiple_files=True
)

def is_valid_us_lat_lon(lat, lon):
    return (24.5 <= lat <= 49.5) and (-125.0 <= lon <= -66.5)

def decode_record(chunk):
    results = []
    for offset in [0, 8, 16]:
        if offset + 16 <= len(chunk):
            try:
                lat, lon = struct.unpack("<dd", chunk[offset:offset+16])
                valid = is_valid_us_lat_lon(lat, lon)
                results.append((offset, lat, lon, valid))
            except:
                results.append((offset, None, None, False))
    return results

def show_file_analysis(file_bytes, label):
    st.subheader(f"📄 {label}")
    header_size = 256
    data = file_bytes[header_size:]
    record_size = 32
    max_records = min(len(data) // record_size, 10)

    for i in range(max_records):
        chunk = data[i*record_size:(i+1)*record_size]
        hex_str = binascii.hexlify(chunk).decode("ascii")
        st.markdown(f"**Record {i+1}** — HEX: `{hex_str}`")
        decoded = decode_record(chunk)
        for offset, lat, lon, valid in decoded:
            if lat is None:
                st.write(f"Offset {offset}: [unpack failed]")
            else:
                status = "✅ Valid US lat/lon" if valid else "❌ Invalid"
                st.write(f"Offset {offset}: lat={lat:.6f}, lon={lon:.6f} → {status}")

if uploaded_files and len(uploaded_files) == 2:
    file1, file2 = uploaded_files
    show_file_analysis(file1.read(), file1.name)
    show_file_analysis(file2.read(), file2.name)
elif uploaded_files and len(uploaded_files) != 2:
    st.warning("Please upload exactly two `.gpl` files.")
