import time
import math
import numpy as np
import pandas as pd
from scipy.spatial import KDTree

# (Giữ nguyên các hàm haversine_np, latlon_to_cartesian, calculate_optimum_azimuth, get_directional_nearest_distance, check_pci_group_validity)

def run_rf_planning(
    df_rim, df_config, df_input, 
    pci_min_dist, rsi_min_dist, mod3_factor, mod6_factor, 
    status_box, progress_bar,
    pci_range=(0, 449), rsi_range=(0, 642)
):
    """Tiến hành phân bổ tham số RF theo Dải PCI và RSI cấu hình từ Textbox."""
    start_time = time.time()
    logs = []

    def add_log(msg):
        logs.append(time.strftime("[%H:%M:%S] ") + msg)

    df_rim.columns = df_rim.columns.str.strip()
    df_config.columns = df_config.columns.str.strip()
    df_input.columns = df_input.columns.str.strip()

    add_log(f"Đọc thành công: RIM ({len(df_rim)} dòng), Config ({len(df_config)} dòng), Input ({len(df_input)} dòng).")
    progress_bar.progress(10)

    df_existing = pd.merge(df_rim, df_config[['Cellname', 'TAC', 'PCI', 'RSI']], on='Cellname', how='inner')
    add_log(f"Tổng hợp {len(df_existing)} cell mạng hiện hữu.")
    progress_bar.progress(20)

    existing_coords_cart = latlon_to_cartesian(df_existing['Lat'].values, df_existing['Lon'].values)
    kdtree_existing = KDTree(existing_coords_cart)

    assigned_pci_list = np.column_stack((existing_coords_cart, df_existing['PCI'].values))
    assigned_rsi_list = np.column_stack((existing_coords_cart, df_existing['RSI'].values))

    # --- TẠO DẢI NHÓM PCI & RSI DỰA TRÊN TEXTBOX INPUT ---
pci_start, pci_end = pci_range
rsi_start, rsi_end = rsi_range

# Tự động chuẩn hóa mốc bắt đầu chia hết cho 3 (PCI) và chia hết cho 6 (RSI)
pci_start = (pci_start // 3) * 3
rsi_start = (rsi_start // 6) * 6

pci_groups = [list(range(i, i + 3)) for i in range(pci_start, pci_end + 1, 3) if i + 2 <= pci_end]
rsi_groups = [[r, (r + 6) % 643, (r + 12) % 643] for r in range(rsi_start, rsi_end + 1, 6)]

    unique_sites = df_input['Sitename'].unique()
    total_sites = len(unique_sites)
    add_log(f"Bắt đầu quy hoạch cho {total_sites} site mới (Sử dụng PCI: {pci_start}-{pci_end}, RSI: {rsi_start}-{rsi_end})...")

    output_rows = []

    for idx, site_name in enumerate(unique_sites):
        status_box.write(f"Đang xử lý site [{idx+1}/{total_sites}]: {site_name}")
        site_cells = df_input[df_input['Sitename'] == site_name].copy()
        site_lat = site_cells['Lat'].iloc[0]
        site_lon = site_cells['Lon'].iloc[0]
        site_cart = latlon_to_cartesian(site_lat, site_lon)[0]

        _, nearest_idx = kdtree_existing.query(site_cart)
        assigned_tac = df_existing.iloc[nearest_idx]['TAC']

        nearest_site_dist = haversine_np(site_lon, site_lat, df_existing.iloc[nearest_idx]['Lon'], df_existing.iloc[nearest_idx]['Lat'])
        nearest_site_dist = max(nearest_site_dist, 100.0)

        neighbor_indices = kdtree_existing.query_ball_point(site_cart, r=5000)
        if len(neighbor_indices) > 0:
            n_lats = df_existing.iloc[neighbor_indices]['Lat'].values
            n_lons = df_existing.iloc[neighbor_indices]['Lon'].values
            n_azs = df_existing.iloc[neighbor_indices]['Azimuth'].values
        else:
            n_lats, n_lons, n_azs = np.array([]), np.array([]), np.array([])

        # --- Phân bổ PCI ---
        selected_pci_group = None
        max_valid_dist = -1
        best_fallback_pci_group = pci_groups[0]
        max_fallback_dist = -1

        mod3_dist_req = min(3000.0, pci_min_dist * mod3_factor)
        mod6_dist_req = min(2000.0, pci_min_dist * mod6_factor)

        for group in pci_groups:
            is_valid, min_d = check_pci_group_validity(group, site_lon, site_lat, assigned_pci_list, pci_min_dist, mod3_dist_req, mod6_dist_req)
            if is_valid:
                if min_d > max_valid_dist:
                    max_valid_dist = min_d
                    selected_pci_group = group
            else:
                if min_d > max_fallback_dist:
                    max_fallback_dist = min_d
                    best_fallback_pci_group = group

        if selected_pci_group is None:
            selected_pci_group = best_fallback_pci_group
            add_log(f"[CẢNH BÁO] Site {site_name}: Chọn nhóm PCI dự phòng tốt nhất (d_min = {int(max_fallback_dist)}m)")

        # --- Phân bổ RSI ---
        selected_rsi_group = None
        max_valid_rsi_dist = -1
        best_fallback_rsi_group = rsi_groups[0]
        max_fallback_rsi_dist = -1

        for group in rsi_groups:
            min_dist_for_this_group = 1e9
            conflict = False
            for rsi_val in group:
                matched_rsis = assigned_rsi_list[assigned_rsi_list[:, 3] == rsi_val]
                if len(matched_rsis) > 0:
                    dists = haversine_np(site_lon, site_lat, np.degrees(np.arctan2(matched_rsis[:, 1], matched_rsis[:, 0])), np.degrees(np.arcsin(np.clip(matched_rsis[:, 2] / 6371000.0, -1.0, 1.0))))
                    current_min_d = np.min(dists)
                    if current_min_d < min_dist_for_this_group:
                        min_dist_for_this_group = current_min_d
                    if current_min_d < rsi_min_dist:
                        conflict = True
                else:
                    min_dist_for_this_group = 1e9

            if not conflict:
                if min_dist_for_this_group > max_valid_rsi_dist:
                    max_valid_rsi_dist = min_dist_for_this_group
                    selected_rsi_group = group
            else:
                if min_dist_for_this_group > max_fallback_rsi_dist:
                    max_fallback_rsi_dist = min_dist_for_this_group
                    best_fallback_rsi_group = group

        if selected_rsi_group is None:
            selected_rsi_group = best_fallback_rsi_group

        # --- Góc Azimuth & Tilt ---
        site_assigned_azs = []
        num_cells = len(site_cells)

        for cell_idx in range(num_cells):
            cell_row = site_cells.iloc[cell_idx].to_dict()
            opt_azimuth = calculate_optimum_azimuth(site_lat, site_lon, n_lats, n_lons, n_azs, sector_idx=cell_idx, total_sectors=num_cells, assigned_site_azimuths=site_assigned_azs)
            site_assigned_azs.append(opt_azimuth)

            m_tilt = 2.0
            ant_height = float(cell_row.get('Height', 30.0))
            cell_directional_dist = get_directional_nearest_distance(site_lat, site_lon, opt_azimuth, n_lats, n_lons, default_dist=nearest_site_dist)
            
            d_coverage = (2.0 / 3.0) * cell_directional_dist
            total_tilt = math.degrees(math.atan(ant_height / d_coverage))
            e_tilt = max(0, int(round(total_tilt - m_tilt)))

            cell_row['TAC'] = int(assigned_tac)
            cell_row['PCI'] = int(selected_pci_group[cell_idx % len(selected_pci_group)])
            cell_row['RSI'] = int(selected_rsi_group[cell_idx % len(selected_rsi_group)])
            cell_row['Azimuth'] = int(opt_azimuth)
            cell_row['M-Tilt'] = int(m_tilt)
            cell_row['E-Tilt'] = int(e_tilt)

            output_rows.append(cell_row)

            assigned_pci_list = np.vstack([assigned_pci_list, [*site_cart, cell_row['PCI']]])
            assigned_rsi_list = np.vstack([assigned_rsi_list, [*site_cart, cell_row['RSI']]])

        progress_bar.progress(20 + int(((idx + 1) / total_sites) * 70))

    df_output = pd.DataFrame(output_rows)
    progress_bar.progress(100)
    elapsed_time = round(time.time() - start_time, 2)
    add_log(f"HOÀN THÀNH: Đã tính toán xong cho {len(output_rows)} cells ({total_sites} sites) trong {elapsed_time} giây.")

    return df_output, "\n".join(logs), elapsed_time
