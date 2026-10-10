import os
import requests
import streamlit as st
from src.config import GITHUB_USER, GITHUB_REPO

@st.cache_data
def get_sample_file_bytes(filename: str):
    """Tải nội dung file mẫu từ thư mục data/ local hoặc GitHub Raw."""
    local_paths = [
        os.path.join("data", filename),
        filename,
        filename.replace("_Sample", "S_Sample")
    ]
    
    for path in local_paths:
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()

    url = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/main/data/{filename}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.content
    except Exception:
        pass

    return None
