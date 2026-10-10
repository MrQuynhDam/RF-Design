import io
import pandas as pd
import streamlit as st

from src.config import CUSTOM_CSS
from src.data_loader import (
    get_sample_file_bytes,
    load_csv_file,
    get_gdrive_file_modified_date,
    GDRIVE_DEFAULT_FILES
)
from src.rf_calculator import run_rf_planning

# 1. Cấu hình trang & CSS
st.set_page_config(
    page_title="LTE RF Design Tool",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

st.title("📡 LTE RF DESIGN AUTOMATION TOOL")
st.caption("Ericsson RAN Systems • Automatic Allocation for TAC, PCI, RSI, Azimuth, M-Tilt & E-Tilt")
st.markdown("---")

# 2. Thanh bên Sidebar
with st.sidebar:
    st.header("⚙️ Cấu Hình Tham Số")

    # Khoảng cách an toàn
    st.subheader("📏 Khoảng cách an toàn")
    pci_min_dist = st.number_input("PCI Min Range (m)", min_value=1000, value=8000, step=500, help="Khoảng cách tối thiểu tái sử dụng PCI")
    rsi_min_dist = st.number_input("RSI Min Range (m)", min_value=1000, value=8000, step=500, help="Khoảng cách tối thiểu tái sử dụng RSI")

    st.markdown("---")

    # Thiết lập dải PCI & RSI bằng Textbox
    st.subheader("🔢 Dải Tham Số Sử Dụng (Range)")

    st.markdown("**Dải PCI Range:**")
    col_pci1, col_pci2 = st.columns(2)
    with col_pci1:
        pci_min_str = st.text_input("PCI Min", value="0", help="Giá trị PCI bắt đầu")
    with col_pci2:
        pci_max_str = st.text_input("PCI Max", value="449", help="Giá trị PCI kết thúc")

    st.markdown("**Dải RSI Range:**")
    col_rsi1, col_rsi2 = st.columns(2)
    with col_rsi1:
        rsi_min_str = st.text_input("RSI Min", value="0", help="Giá trị RSI bắt đầu")
    with col_rsi2:
        rsi_max_str = st.text_input("RSI Max", value="642", help="Giá trị RSI kết thúc")

    st.markdown("---")

    # Ràng buộc Modulo
    st.subheader("🛡️ Ràng buộc Modulo")
    mod3_factor = st.slider("Bảo vệ Mod3 (% PCI Range)", min_value=10, max_value=100, value=40, step=5) / 100.0
    mod6_factor = st.slider("Bảo vệ Mod6 (% PCI Range)", min_value=10, max_value=100, value=25, step=5) / 100.0

# 3. Lấy ngày Modify động từ Google Drive
rims_date = get_gdrive_file_modified_date(GDRIVE_DEFAULT_FILES["RIMS.csv"])
config_date = get_gdrive_file_modified_date(GDRIVE_DEFAULT_FILES["Config.csv"])

# 4. Khu vực Input & Download Sample
col_left, col_right = st.columns([1, 2], gap="medium")

with col_left:
    st.markdown('<div class="section-title">📥 1. Download Sample Files</div>', unsafe_allow_html=True)
    sample_files = {
        "RIMS.csv": f"File thông tin Trạm RIM (Mặc định ngày {rims_date})",
        "Config.csv": f"File cấu hình Cell (Mặc định ngày {config_date})",
        "Input_Sample.csv": "File danh sách Site mới cần quy hoạch"
    }

    for fname, fdesc in sample_files.items():
        file_bytes = get_sample_file_bytes(fname)
        if file_bytes:
            st.download_button(
                label="📄 " + fname,
                data=file_bytes,
                file_name=fname,
                mime="text/csv",
                use_container_width=True,
                help=fdesc
            )
        else:
            st.button(f"❌ Không tìm thấy {fname}", disabled=True, use_container_width=True)

with col_right:
    st.markdown('<div class="section-title">📤 2. Upload input files</div>', unsafe_allow_html=True)
    u1, u2, u3 = st.columns(3)
    with u1:
        rim_file = st.file_uploader(f"1. RIMS.csv :yellow[(Mặc định sử dụng dữ liệu RIMs ngày {rims_date})]", type=["csv"], key="rim")
    with u2:
        config_file = st.file_uploader(f"2. Config.csv :yellow[(Mặc định sử dụng dữ liệu Config ngày {config_date})]", type=["csv"], key="config")        
    with u3:
        input_file = st.file_uploader("3. Input.csv (Upload thông tin các site/cell cần thiết kế RF)", type=["csv"], key="input")

st.markdown("---")
col_btn, _ = st.columns([1, 2])
with col_btn:
    execute_btn = st.button("🚀 BẮT ĐẦU QUY HOẠCH RF", type="primary", use_container_width=True)

# 5. Thực thi tính toán quy hoạch RF
if execute_btn:
    try:
        pci_start = int(pci_min_str.strip())
        pci_end = int(pci_max_str.strip())
        rsi_start = int(rsi_min_str.strip())
        rsi_end = int(rsi_max_str.strip())
        valid_range = True
    except ValueError:
        st.error("⚠️ Giá trị dải PCI và RSI nhập vào textbox phải là số nguyên!")
        valid_range = False

    if valid_range:
        status_box = st.status("⚙️ Đang tiến hành phân bổ tham số RF...", expanded=True)
        progress_bar = st.progress(0)

        try:
            status_box.write("Đang tải dữ liệu RIMS, Config và Input...")

            # 1. Đọc RIMS: Upload > Google Drive
            df_rim = load_csv_file(
                uploaded_file=rim_file,
                default_gdrive_id=GDRIVE_DEFAULT_FILES["RIMS.csv"],
                local_path="data/RIMS_Sample.csv"
            )

            # 2. Đọc Config: Upload > Google Drive
            df_config = load_csv_file(
                uploaded_file=config_file,
                default_gdrive_id=GDRIVE_DEFAULT_FILES["Config.csv"],
                local_path="data/Config_Sample.csv"
            )

            # 3. Đọc Input: Upload > Sample
            df_input = load_csv_file(
                uploaded_file=input_file,
                local_path="data/Input_Sample.csv"
            )

            if df_rim is None or df_config is None or df_input is None:
                status_box.update(label="❌ Thiếu dữ liệu đầu vào!", state="error")
                st.error("⚠️ Không thể đọc file dữ liệu. Vui lòng kiểm tra kết nối Google Drive hoặc upload file!")
            elif pci_start >= pci_end:
                st.error("⚠️ Giá trị 'PCI Min' phải nhỏ hơn 'PCI Max'!")
            elif rsi_start >= rsi_end:
                st.error("⚠️ Giá trị 'RSI Min' phải nhỏ hơn 'RSI Max'!")
            else:
                df_output, logs_text, elapsed_time = run_rf_planning(
                    df_rim, df_config, df_input,
                    pci_min_dist, rsi_min_dist, mod3_factor, mod6_factor,
                    status_box, progress_bar,
                    pci_range=(pci_start, pci_end),
                    rsi_range=(rsi_start, rsi_end)
                )

                status_box.update(label="✅ Hoàn tất quy hoạch thành công!", state="complete", expanded=False)
                st.session_state["output_df"] = df_output
                st.session_state["logs"] = logs_text
                st.session_state["exec_time"] = elapsed_time

        except Exception as e:
            status_box.update(label="❌ Có lỗi xảy ra trong quá trình xử lý!", state="error")
            st.error(f"Chi tiết lỗi: {str(e)}")

# 6. Hiển thị Dashboard Kết quả
if "output_df" in st.session_state:
    st.markdown("### 📊 Kết Quả Quy Hoạch")
    df_out = st.session_state["output_df"]
    exec_t = st.session_state.get("exec_time", 0)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Site Mới", f"{df_out['Sitename'].nunique()}")
    m2.metric("Tổng Cell Phân Bổ", f"{len(df_out)}")
    m3.metric("Góc E-Tilt Trung Bình", f"{df_out['E-Tilt'].mean():.1f}°")
    m4.metric("Thời Gian Xử Lý", f"{exec_t}s")

    tab_data, tab_log = st.tabs(["📋 Danh Sách Kết Quả (Output Data)", "📜 Nhật Ký Xử Lý (Logs)"])

    with tab_data:
        st.dataframe(df_out, use_container_width=True, height=380)
        csv_buffer = io.StringIO()
        df_out.to_csv(csv_buffer, index=False)
        st.download_button(
            label="📥 Tải Về Kết Quả Quy Hoạch (Output_RF_Design.csv)",
            type="primary",
            data=csv_buffer.getvalue().encode('utf-8-sig'),
            file_name="Output_RF_Design.csv",
            mime="text/csv"
        )

    with tab_log:
        st.code(st.session_state.get("logs", ""), language="text")
