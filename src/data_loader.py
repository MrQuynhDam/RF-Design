import os
import io
import re
import requests
import pandas as pd
import streamlit as st
from datetime import datetime
from email.utils import parsedate_to_datetime
from src.config import GITHUB_USER, GITHUB_REPO

# File ID Google Drive mặc định
GDRIVE_DEFAULT_FILES = {
    "RIMS.csv": "1bYv7Ep37WYjdKYmJqx3AovNadeRii_AM",
    "Config.csv": "1BnvTWG-W_qyqBBxrUhbkki__g2CaRDA-"
}


@st.cache_data(ttl=3600)
def get_gdrive_file_modified_date(file_id: str) -> str:
    """Tự động lấy ngày cập nhật cuối cùng (Modify Date) của file trên Google Drive (định dạng dd/mm/yyyy)."""
    url = f"https://drive.google.com/file/d/{file_id}/view"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            # 1. Tìm timestamp trong metadata script của Google Drive page
            match = re.search(r'"modifiedTime"\s*:\s*"([^"]+)"', response.text)
            if match:
                iso_str = match.group(1)
                dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
                return dt.strftime("%d/%m/%Y")

            # 2. Fallback kiểm tra header HTTP nếu có
            if 'Last-Modified' in response.headers:
                dt = parsedate_to_datetime(response.headers['Last-Modified'])
                return dt.strftime("%d/%m/%Y")
    except Exception:
        pass

    return "mới nhất"


@st.cache_data(ttl=3600)
def fetch_gdrive_file(file_id: str):
    """Tải nội dung file trực tiếp từ link Google Drive public."""
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.content
    except Exception as e:
        st.error(f"Không thể tải file từ Google Drive: {e}")
    return None


def load_csv_file(uploaded_file, default_gdrive_id=None, local_path=None):
    """
    Thứ tự ưu tiên nạp dữ liệu:
    1. File người dùng upload
    2. File mặc định trên Google Drive
    3. File mẫu local
    """
    if uploaded_file is not None:
        return pd.read_csv(uploaded_file)

    if default_gdrive_id:
        content = fetch_gdrive_file(default_gdrive_id)
        if content:
            return pd.read_csv(io.BytesIO(content))

    if local_path and os.path.exists(local_path):
        return pd.read_csv(local_path)

    return None


@st.cache_data
def get_sample_file_bytes(filename: str):
    """Tải nội dung file mẫu để người dùng download."""
    local_paths = [
        os.path.join("data", filename),
        filename,
        filename.replace("_Sample", "S_Sample")
    ]

    for path in local_paths:
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()

    if filename in GDRIVE_DEFAULT_FILES:
        content = fetch_gdrive_file(GDRIVE_DEFAULT_FILES[filename])
        if content:
            return content

    url = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/main/data/{filename}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.content
    except Exception:
        pass

    return None
