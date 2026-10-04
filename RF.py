import os
import time
import math
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import pandas as pd
import numpy as np
from scipy.spatial import KDTree

# ==========================================
# RF CORE CALCULATIONS & UTILS
# ==========================================

def haversine_np(lon1, lat1, lon2, lat2):
    """Tính khoảng cách theo mét giữa các tọa độ GPS (Vectorized)."""
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    km = 6367 * c
    return km * 1000.0  # trả về mét

def latlon_to_cartesian(lat, lon):
    """Chuyển đổi Lat/Lon sang tọa độ x,y,z xấp xỉ trên mặt cầu (mét) dùng cho KDTree."""
    R = 6371000.0
    lat_rad = np.radians(lat)
    lon_rad = np.radians(lon)
    x = R * np.cos(lat_rad) * np.cos(lon_rad)
    y = R * np.cos(lat_rad) * np.sin(lon_rad)
    z = R * np.sin(lat_rad)
    return np.column_stack((x, y, z))

def is_azimuth_in_sector(azimuth, sector_idx):
    """Kiểm tra Azimuth có nằm trong dải cho phép của Sector không."""
    azimuth = azimuth % 360
    if sector_idx == 0:  # Sector 1: 300 -> 60
        return (azimuth >= 300) or (azimuth <= 60)
    elif sector_idx == 1:  # Sector 2: 60 -> 180
        return 60 <= azimuth <= 180
    elif sector_idx == 2:  # Sector 3: 180 -> 300
        return 180 <= azimuth <= 300
    return False

def calculate_optimum_azimuth(site_lat, site_lon, neighbor_lats, neighbor_lons, neighbor_azimuths, sector_idx):
    """
    Tìm Azimuth tối ưu cho Cell:
    - Nằm trong dải quy định của Sector.
    - Tránh hướng ngắm đối diện (face-to-face) với các cell lân cận.
    """
    default_azimuths = [30, 120, 240]
    best_azimuth = default_azimuths[sector_idx]
    max_score = -1e9

    # Tạo danh sách các hướng azimuth thử nghiệm theo bước 5 độ
    if sector_idx == 0:
        candidates = list(range(300, 360, 5)) + list(range(0, 65, 5))
    elif sector_idx == 1:
        candidates = list(range(60, 185, 5))
    else:
        candidates = list(range(180, 305, 5))

    if len(neighbor_lats) == 0:
        return best_azimuth

    # Tọa độ vector các lân cận
    dlat = np.radians(neighbor_lats - site_lat)
    dlon = np.radians(neighbor_lons - site_lon)
    # Bearing từ current site tới neighbor sites
    y = np.sin(dlon) * np.cos(np.radians(neighbor_lats))
    x = np.cos(np.radians(site_lat)) * np.sin(np.radians(neighbor_lats)) - \
        np.sin(np.radians(site_lat)) * np.cos(np.radians(neighbor_lats)) * np.cos(dlon)
    bearings_to_neighbors = (np.degrees(np.arctan2(y, x)) + 360) % 360

    for az in candidates:
        # Tính mức độ lệch hướng trực diện
        # Hướng bắn của candidate az so với vị trí neighbor
        angle_diff1 = np.abs((az - bearings_to_neighbors + 180) % 360 - 180)
        # Hướng bắn của neighbor cell ngược lại
        neighbor_boresight = (bearings_to_neighbors + 180) % 360
        angle_diff2 = np.abs((neighbor_azimuths - neighbor_boresight + 180) % 360 - 180)
        
        # Điểm phạt cao nếu 2 cell hướng thẳng vào nhau
        penalty = np.sum(np.exp(-((angle_diff1**2 + angle_diff2**2) / (2 * 30**2))))
        score = -penalty

        if score > max_score:
            max_score = score
            best_azimuth = az

    return best_azimuth

# ==========================================
# GUI APPLICATION
# ==========================================

class RFDesignApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LTE RF Design Tool")
        self.geometry("900x700")
        self.minsize(800, 600)

        # Theme & Styling
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        
        self.create_widgets()

    def create_widgets(self):
        # Header Frame
        header_frame = tk.Frame(self, bg="#003366", height=60)
        header_frame.pack(fill=tk.X, side=tk.TOP)
        header_label = tk.Label(
            header_frame, 
            text="LTE RF DESIGN AUTOMATION", 
            font=("Helvetica", 14, "bold"), 
            fg="white", 
            bg="#003366"
        )
        header_label.pack(side=tk.LEFT, padx=20, pady=15)

        # Main Container
        main_frame = ttk.Frame(self, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. File Selection Section
        file_frame = ttk.LabelFrame(main_frame, text=" File Inputs ", padding="10")
        file_frame.pack(fill=tk.X, pady=5)

        self.rim_path = tk.StringVar()
        self.config_path = tk.StringVar()
        self.input_path = tk.StringVar()

        self._create_file_row(file_frame, "RIM.csv (Physical):", self.rim_path, 0)
        self._create_file_row(file_frame, "Config.csv (Logic):", self.config_path, 1)
        self._create_file_row(file_frame, "Input.csv (New Sites):", self.input_path, 2)

        # 2. Parameters Section
        param_frame = ttk.LabelFrame(main_frame, text=" Design Parameters ", padding="10")
        param_frame.pack(fill=tk.X, pady=5)

        ttk.Label(param_frame, text="PCI Reuse Distance Range (m):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.pci_range_var = tk.StringVar(value="8000")
        ttk.Entry(param_frame, textvariable=self.pci_range_var, width=15).grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Label(param_frame, text="RSI Reuse Distance Range (m):").grid(row=0, column=2, sticky=tk.W, padx=15, pady=5)
        self.rsi_range_var = tk.StringVar(value="8000")
        ttk.Entry(param_frame, textvariable=self.rsi_range_var, width=15).grid(row=0, column=3, sticky=tk.W, padx=5, pady=5)

        # 3. Action & Progress Section
        action_frame = ttk.Frame(main_frame, padding="5")
        action_frame.pack(fill=tk.X, pady=5)

        self.btn_run = ttk.Button(action_frame, text="Execute RF Design", command=self.start_processing_thread)
        self.btn_run.pack(side=tk.LEFT, padx=5)

        self.progress_bar = ttk.Progressbar(action_frame, orient="horizontal", mode="determinate")
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        # 4. Log Output Section
        log_frame = ttk.LabelFrame(main_frame, text=" Process Execution Logs ", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, state='disabled', font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _create_file_row(self, parent, label_text, var, row):
        ttk.Label(parent, text=label_text).grid(row=row, column=0, sticky=tk.W, padx=5, pady=3)
        ttk.Entry(parent, textvariable=var, width=65).grid(row=row, column=1, padx=5, pady=3)
        ttk.Button(parent, text="Browse...", command=lambda: self._browse_file(var)).grid(row=row, column=2, padx=5, pady=3)

    def _browse_file(self, var):
        filename = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if filename:
            var.set(filename)

    def log(self, message):
        """Ghi log vào UI theo chuẩn thời gian."""
        self.log_text.config(state='normal')
        timestamp = time.strftime("[%H:%M:%S] ")
        self.log_text.insert(tk.END, timestamp + message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')

    def set_progress(self, val):
        self.progress_bar['value'] = val
        self.update_idletasks()

    def start_processing_thread(self):
        # Validate inputs
        if not os.path.exists(self.rim_path.get()) or \
           not os.path.exists(self.config_path.get()) or \
           not os.path.exists(self.input_path.get()):
            messagebox.showerror("Error", "Vui lòng chọn đầy đủ và chính xác đường dẫn 3 file CSV đầu vào!")
            return

        try:
            pci_range = float(self.pci_range_var.get())
            rsi_range = float(self.rsi_range_var.get())
        except ValueError:
            messagebox.showerror("Error", "PCI Range và RSI Range phải là số hợp lệ!")
            return

        self.btn_run.config(state='disabled')
        threading.Thread(target=self.run_rf_design, args=(pci_range, rsi_range), daemon=True).start()

    # ==========================================
    # CORE PROCESSING ENGINE
    # ==========================================
    def run_rf_design(self, pci_min_dist, rsi_min_dist):
        start_time = time.time()
        self.log("Bắt đầu tiến trình thiết kế RF...")
        self.set_progress(0)

        try:
            # Step 1: Read CSVs
            self.log("Đang đọc các dữ liệu đầu vào...")
            df_rim = pd.read_csv(self.rim_path.get())
            df_config = pd.read_csv(self.config_path.get())
            df_input = pd.read_csv(self.input_path.get())

            self.log(f"-> RIM: {len(df_rim)} rows, Config: {len(df_config)} rows, Input: {len(df_input)} rows.")
            self.set_progress(10)

            # Standardize Column Names
            df_rim.columns = df_rim.columns.str.strip()
            df_config.columns = df_config.columns.str.strip()
            df_input.columns = df_input.columns.str.strip()

            # Merge RIM + Config for Existing Sites
            df_existing = pd.merge(df_rim, df_config[['Cellname', 'TAC', 'PCI', 'RSI']], on='Cellname', how='inner')
            self.log(f"-> Tổng hợp thành công {len(df_existing)} cell hiện hữu.")
            self.set_progress(20)

            # Build Spatial Index (KDTree) for Existing Sites
            existing_coords_cart = latlon_to_cartesian(df_existing['Lat'].values, df_existing['Lon'].values)
            kdtree_existing = KDTree(existing_coords_cart)

            # Tracking structures for assigned PCIs/RSIs
            # Matrix of existing allocated PCI/RSI positions: [x, y, z, value]
            assigned_pci_list = np.column_stack((existing_coords_cart, df_existing['PCI'].values))
            assigned_rsi_list = np.column_stack((existing_coords_cart, df_existing['RSI'].values))

            # Valid Groups
            # PCI Groups: 0-449, bộ 3 liên tiếp: (0,1,2), (3,4,5)...
            pci_groups = [list(range(i, i+3)) for i in range(0, 448, 3)]
            # RSI Groups: 0-642, bước 6: (0, 6, 12), (6, 12, 18), ...
            rsi_groups = [[r, (r+6)%643, (r+12)%643] for r in range(0, 643-12, 6)]

            # Group Input by Site
            unique_sites = df_input['Sitename'].unique()
            total_sites = len(unique_sites)
            self.log(f"Bắt đầu quy hoạch cho {total_sites} site mới...")

            output_rows = []

            for idx, site_name in enumerate(unique_sites):
                site_cells = df_input[df_input['Sitename'] == site_name].copy()
                site_lat = site_cells['Lat'].iloc[0]
                site_lon = site_cells['Lon'].iloc[0]
                site_cart = latlon_to_cartesian(site_lat, site_lon)[0]

                # 1. TAC Allocation (From Nearest Existing Site)
                _, nearest_idx = kdtree_existing.query(site_cart)
                assigned_tac = df_existing.iloc[nearest_idx]['TAC']

                # Distance to Nearest Existing Site (for E-Tilt calculation)
                nearest_site_dist = haversine_np(
                    site_lon, site_lat, 
                    df_existing.iloc[nearest_idx]['Lon'], df_existing.iloc[nearest_idx]['Lat']
                )
                nearest_site_dist = max(nearest_site_dist, 100.0) # avoid division by zero

                # Find Neighbors around site within 3km for Azimuth Optimization
                neighbor_indices = kdtree_existing.query_ball_point(site_cart, r=3000)
                if len(neighbor_indices) > 0:
                    n_lats = df_existing.iloc[neighbor_indices]['Lat'].values
                    n_lons = df_existing.iloc[neighbor_indices]['Lon'].values
                    n_azs = df_existing.iloc[neighbor_indices]['Azimuth'].values
                else:
                    n_lats, n_lons, n_azs = np.array([]), np.array([]), np.array([])

                # 2. Allocate PCI Group for the 3 cells
                selected_pci_group = None
                for group in pci_groups:
                    conflict = False
                    for pci_val in group:
                        # Check distance to all existing/assigned cells with SAME PCI
                        matched_pcis = assigned_pci_list[assigned_pci_list[:, 3] == pci_val]
                        if len(matched_pcis) > 0:
                            dists = haversine_np(site_lon, site_lat, 
                                                 np.degrees(np.arctan2(matched_pcis[:,1], matched_pcis[:,0])), 
                                                 np.degrees(np.arcsin(matched_pcis[:,2]/6371000.0)))
                            if np.min(dists) < pci_min_dist:
                                conflict = True
                                break
                    if not conflict:
                        selected_pci_group = group
                        break

                if selected_pci_group is None:
                    selected_pci_group = pci_groups[idx % len(pci_groups)] # Fallback

                # 3. Allocate RSI Group for the 3 cells
                selected_rsi_group = None
                for group in rsi_groups:
                    conflict = False
                    for rsi_val in group:
                        matched_rsis = assigned_rsi_list[assigned_rsi_list[:, 3] == rsi_val]
                        if len(matched_rsis) > 0:
                            dists = haversine_np(site_lon, site_lat, 
                                                 np.degrees(np.arctan2(matched_rsis[:,1], matched_rsis[:,0])), 
                                                 np.degrees(np.arcsin(matched_rsis[:,2]/6371000.0)))
                            if np.min(dists) < rsi_min_dist:
                                conflict = True
                                break
                    if not conflict:
                        selected_rsi_group = group
                        break

                if selected_rsi_group is None:
                    selected_rsi_group = rsi_groups[idx % len(rsi_groups)] # Fallback

                # Process 3 cells for this site
                for cell_idx in range(min(3, len(site_cells))):
                    cell_row = site_cells.iloc[cell_idx].to_dict()

                    # Azimuth
                    opt_azimuth = calculate_optimum_azimuth(
                        site_lat, site_lon, n_lats, n_lons, n_azs, sector_idx=cell_idx
                    )

                    # Tilt Calculation
                    # Standard M-Tilt = 2
                    m_tilt = 2.0
                    ant_height = float(cell_row.get('Antenna Height', 30.0))
                    
                    # Target coverage distance = 2/3 distance to nearest neighbor site
                    d_coverage = (2.0 / 3.0) * nearest_site_dist
                    total_tilt = math.degrees(math.atan(ant_height / d_coverage))
                    
                    # Electrical Tilt = Total Tilt - Mechanical Tilt
                    e_tilt = max(0, int(round(total_tilt - m_tilt)))

                    # Assign Attributes
                    cell_row['TAC'] = int(assigned_tac)
                    cell_row['PCI'] = int(selected_pci_group[cell_idx])
                    cell_row['RSI'] = int(selected_rsi_group[cell_idx])
                    cell_row['Azimuth'] = int(opt_azimuth)
                    cell_row['M-Tilt'] = int(m_tilt)
                    cell_row['E-Tilt'] = int(e_tilt)

                    output_rows.append(cell_row)

                    # Register newly assigned PCI/RSI to avoid reusing in subsequent sites
                    assigned_pci_list = np.vstack([assigned_pci_list, [*site_cart, cell_row['PCI']]])
                    assigned_rsi_list = np.vstack([assigned_rsi_list, [*site_cart, cell_row['RSI']]])

                # Update Progress
                progress = 20 + int(((idx + 1) / total_sites) * 70)
                self.set_progress(progress)

            # Step 4: Export Result File
            df_output = pd.DataFrame(output_rows)
            output_filepath = os.path.join(os.path.dirname(self.input_path.get()), "Output_RF_Design.csv")
            df_output.to_csv(output_filepath, index=False)

            self.set_progress(100)
            elapsed_time = round(time.time() - start_time, 2)
            
            self.log("="*50)
            self.log(f"THÀNH CÔNG: Đã hoàn tất quy hoạch RF!")
            self.log(f"- File đầu ra: {output_filepath}")
            self.log(f"- Thống kê: Hoàn thành thiết kế cho {len(output_rows)} cells ({total_sites} sites).")
            self.log(f"- Tổng thời gian thực thi: {elapsed_time} giây.")
            self.log("="*50)

            messagebox.showinfo("Success", f"Đã xuất file kết quả thành công!\nTổng thời gian: {elapsed_time}s")

        except Exception as e:
            self.log(f"LỖI HỆ THỐNG: {str(e)}")
            messagebox.showerror("Execution Error", f"Đã xảy ra lỗi trong quá trình thực thi:\n{str(e)}")
        finally:
            self.btn_run.config(state='normal')

if __name__ == "__main__":
    app = RFDesignApp()
    app.mainloop()
