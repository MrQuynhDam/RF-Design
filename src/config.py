# Cấu hình GitHub Repository để đọc file mẫu online
GITHUB_USER = "MrQuynhDam"
GITHUB_REPO = "RF-Design-online"

# Custom CSS giao diện ứng dụng Streamlit
CUSTOM_CSS = """
    <style>
    .main {
        background-color: #f8f9fa;
    }
    
    .custom-card {
        background-color: #ffffff;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
        border: 1px solid #e9ecef;
        margin-bottom: 20px;
    }
    
    div[data-testid="stFileUploaderDropzoneInstructions"] > * {
        display: none !important;
    }
    div[data-testid="stFileUploaderDropzoneInstructions"]::after {
        content: "Kéo thả hoặc chọn file CSV (Max 10MB)";
        font-size: 13px;
        color: #6c757d;
    }
    
    .section-title {
        font-size: 1.1rem;
        font-weight: 600;
        color: #4d648a;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    div.stButton > button[kind="primary"] {
        background-color: #2563eb;
        border-color: #2563eb;
        font-weight: 600;
        border-radius: 6px;
        height: 46px;
    }
    </style>
"""
