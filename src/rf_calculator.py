import time
import math
import re
import numpy as np
import pandas as pd
from scipy.spatial import KDTree


def extract_sector_id(cell_name: str, site_name: str = "") -> str:
    """
    Tự động trích xuất ID Sector vật lý dựa trên CHỮ SỐ CUỐI CÙNG của mã cell.
    Ví dụ:
    - M11, M31, M51 -> Sector '1'
    - M12, M32, M52 -> Sector '2'
    - M13, M33, M53 -> Sector '3'
    """
    clean_cell = str(cell_name).strip()

    match = re.search(r'(\d)(?:-[A-Za-z0-9]+)?$', clean_cell)
    if match:
        return match.group(1)

    return clean_cell


def haversine_np(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    c = 2 * np.arcsin(np.sqrt(a))
    return c * 6371000.0


def latlon_to_cartesian(lat, lon):
    R = 6371000.0
    lat_rad = np.radians(lat)
    lon_rad = np.radians(lon)
    x = R * np.cos(lat_rad) * np.cos(lon_rad)
    y = R * np.cos(lat_rad) * np.sin(lon_rad)
    z = R * np.sin(lat_rad)
    return np.column_stack((x, y, z))


def calculate_optimum_azimuth(site_lat, site_lon, neighbor_lats, neighbor_lons, neighbor_azimuths, sector_idx, total_sectors=3, assigned_site_azimuths=None):
    if assigned_site_azimuths is None:
        assigned_site_azimuths = []

    base_angle = 360.0 / total_sectors
    default_azimuth = int((sector_idx * base_angle) % 360)
    best_azimuth = default_azimuth
    max_score = -1e9

    start_angle = int((default_azimuth - 30) % 360)
    end_angle = int((default_azimuth + 35) % 360)

    if start_angle < end_angle:
        candidates = list(range(start_angle, end_angle, 5))
    else:
        candidates = list(range(start_angle, 360, 5)) + list(range(0, end_angle, 5))

    valid_candidates = []
    for az in candidates:
        valid = True
        for prev_az in assigned_site_azimuths:
            diff = np.abs((az - prev_az + 180) % 360 - 180)
            if diff < (360 / total_sectors) * 0.6:
                valid = False
                break
        if valid:
            valid_candidates.append(az)

    if not valid_candidates:
        valid_candidates = candidates if candidates else [default_azimuth]

    if len(neighbor_lats) == 0:
        return min(valid_candidates, key=lambda x: np.abs((x - default_azimuth + 180) % 360 - 180))

    dlat = np.radians(neighbor_lats - site_lat)
    dlon = np.radians(neighbor_lons - site_lon)
    y = np.sin(dlon) * np.cos(np.radians(neighbor_lats))
    x = np.cos(np.radians(site_lat)) * np.sin(np.radians(neighbor_lats)) - \
        np.sin(np.radians(site_lat)) * np.cos(np.radians(neighbor_lats)) * np.cos(dlon)
    bearings_to_neighbors = (np.degrees(np.arctan2(y, x)) + 360) % 360

    for az in valid_candidates:
        angle_diff1 = np.abs((az - bearings_to_neighbors + 180) % 360 - 180)
        neighbor_boresight = (bearings_to_neighbors + 180) % 360
        angle_diff2 = np.abs((neighbor_azimuths - neighbor_boresight + 180) % 360 - 180)

        penalty = np.sum(np.exp(-((angle_diff1 ** 2 + angle_diff2 ** 2) / (2 * 30 ** 2))))
        score = -penalty

        if score > max_score:
            max_score = score
            best_azimuth = az

    return best_azimuth


def get_directional_nearest_distance(site_lat, site_lon, cell_azimuth, neighbor_lats, neighbor_lons, default_dist=1500.0):
    if len(neighbor_lats) == 0:
        return default_dist

    dlat = np.radians(neighbor_lats - site_lat)
    dlon = np.radians(neighbor_lons - site_lon)
    y = np.sin(dlon) * np.cos(np.radians(neighbor_lats))
    x = np.cos(np.radians(site_lat)) * np.sin(np.radians(neighbor_lats)) - \
        np.sin(np.radians(site_lat)) * np.cos(np.radians(neighbor_lats)) * np.cos(dlon)
    bearings = (np.degrees(np.arctan2(y, x)) + 360) % 360

    angle_diffs = np.abs((bearings - cell_azimuth + 180) % 360 - 180)
    in_cone_mask = angle_diffs <= 45

    if not np.any(in_cone_mask):
        return default_dist

    dists = haversine_np(site_lon, site_lat, neighbor_lons[in_cone_mask], neighbor_lats[in_cone_mask])
    return max(np.min(dists), 100.0)


def check_pci_group_validity(candidate_group, site_lon, site_lat, assigned_pci_list, pci_min_dist, mod3_min_dist, mod6_min_dist):
    if len(assigned_pci_list) == 0:
        return True, 1e9

    min_pci_dist = 1e9
    assigned_lons = np.degrees(np.arctan2(assigned_pci_list[:, 1], assigned_pci_list[:, 0]))
    assigned_lats = np.degrees(np.arcsin(np.clip(assigned_pci_list[:, 2] / 6371000.0, -1.0, 1.0)))
    assigned_pcis = assigned_pci_list[:, 3].astype(int)

    dists = haversine_np(site_lon, site_lat, assigned_lons, assigned_lats)

    for pci_candidate in candidate_group:
        cand_mod3 = pci_candidate % 3
        cand_mod6 = pci_candidate % 6

        same_pci_mask = (assigned_pcis == pci_candidate)
        if np.any(same_pci_mask):
            d = np.min(dists[same_pci_mask])
            if d < min_pci_dist:
                min_pci_dist = d
            if d < pci_min_dist:
                return False, min_pci_dist

        same_mod3_mask = ((assigned_pcis % 3) == cand_mod3)
        if np.any(same_mod3_mask):
            d_mod3 = np.min(dists[same_mod3_mask])
            if d_mod3 < mod3_min_dist:
                return False, min_pci_dist

        same_mod6_mask = ((assigned_pcis % 6) == cand_mod6)
        if np.any(same_mod6_mask):
            d_mod6 = np.min(dists[same_mod6_mask])
            if d_mod6 < mod6_min_dist:
                return False, min_pci_dist

    return True, min_pci_dist


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

    pci_start = (pci_start // 3) * 3
    # Mốc bắt đầu RSI chia hết cho 18 (bội số của 9 và bước nhảy 18 giữa các trạm)
    rsi_start = (rsi_start // 18) * 18

    pci_groups = [list(range(i, i + 3)) for i in range(pci_start, pci_end + 1, 3) if i + 2 <= pci_end]
    if not pci_groups:
        pci_groups = [[pci_start, pci_start + 1, pci_start + 2]]

    # Mỗi nhóm RSI cho 3 sector: [r, r + 6, r + 12] (không dùng modulo làm lệch giá trị)
    rsi_groups = [[r, r + 6, r + 12] for r in range(rsi_start, rsi_end + 1, 18) if r + 12 <= rsi_end]
    if not rsi_groups:
        rsi_groups = [[rsi_start, rsi_start + 6, rsi_start + 12]]

    unique_sites = df_input['Sitename'].unique()
    total_sites = len(unique_sites)
    add_log(f"Bắt đầu quy hoạch cho {total_sites} site mới (Sử dụng PCI: {pci_start}-{pci_end}, RSI: {rsi_start}-{rsi_end})...")

    output_rows = []

    for idx, site_name in enumerate(unique_sites):
        status_box.write(f"Đang xử lý site [{idx+1}/{total_sites}]: {site_name}")
        site_cells = df_input[df_input['Sitename'] == site_name].copy()

        # 1. Trích xuất nhóm Sector ID theo số CUỐI CÙNG của từng Cell
        site_cells['Sector_ID'] = site_cells['Cellname'].apply(lambda c: extract_sector_id(c, site_name))
        unique_sectors = list(dict.fromkeys(site_cells['Sector_ID']))
        num_sectors = len(unique_sectors)

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

        # 2. Phân bổ Nhóm PCI Best-Fit cho Site
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

        # 3. Phân bổ Nhóm RSI Best-Fit cho Site
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

        # 4. Tính toán Tham số RF cho từng SECTOR VẬT LÝ
        sector_params = {}
        site_assigned_azs = []

        for sec_idx, sec_id in enumerate(unique_sectors):
            sec_cells = site_cells[site_cells['Sector_ID'] == sec_id]
            first_cell = sec_cells.iloc[0]

            opt_azimuth = calculate_optimum_azimuth(
                site_lat, site_lon, n_lats, n_lons, n_azs,
                sector_idx=sec_idx,
                total_sectors=num_sectors,
                assigned_site_azimuths=site_assigned_azs
            )
            site_assigned_azs.append(opt_azimuth)

            m_tilt = 2.0
            ant_height = float(first_cell.get('Height', 30.0))
            cell_directional_dist = get_directional_nearest_distance(site_lat, site_lon, opt_azimuth, n_lats, n_lons, default_dist=nearest_site_dist)

            d_coverage = (2.0 / 3.0) * cell_directional_dist
            raw_total_tilt = math.degrees(math.atan(ant_height / d_coverage))

            # Giới hạn TotalTilt tối thiểu >= 3°
            calculated_total_tilt = max(3.0, raw_total_tilt)
            e_tilt = max(0, int(round(calculated_total_tilt - m_tilt)))
            
            actual_total_tilt = int(m_tilt + e_tilt)
            if actual_total_tilt < 3:
                actual_total_tilt = 3
                e_tilt = actual_total_tilt - int(m_tilt)

            pci_val = int(selected_pci_group[sec_idx % len(selected_pci_group)])
            rsi_val = int(selected_rsi_group[sec_idx % len(selected_rsi_group)])

            sector_params[sec_id] = {
                'TAC': int(assigned_tac),
                'PCI': pci_val,
                'RSI': rsi_val,
                'Azimuth': int(opt_azimuth),
                'M-Tilt': int(m_tilt),
                'E-Tilt': int(e_tilt),
                'TotalTilt': int(actual_total_tilt)
            }

            assigned_pci_list = np.vstack([assigned_pci_list, [*site_cart, pci_val]])
            assigned_rsi_list = np.vstack([assigned_rsi_list, [*site_cart, rsi_val]])

        # 5. Đồng bộ tham số cho TẤT CẢ các Cell thuộc cùng Sector
        for _, cell_row_s in site_cells.iterrows():
            cell_row = cell_row_s.to_dict()
            sec_id = cell_row.pop('Sector_ID', None)
            s_param = sector_params[sec_id]

            cell_row['TAC'] = s_param['TAC']
            cell_row['PCI'] = s_param['PCI']
            cell_row['RSI'] = s_param['RSI']
            cell_row['Azimuth'] = s_param['Azimuth']
            cell_row['M-Tilt'] = s_param['M-Tilt']
            cell_row['E-Tilt'] = s_param['E-Tilt']
            cell_row['TotalTilt'] = s_param['TotalTilt']

            output_rows.append(cell_row)

        progress_bar.progress(20 + int(((idx + 1) / total_sites) * 70))

    df_output = pd.DataFrame(output_rows)
    progress_bar.progress(100)
    elapsed_time = round(time.time() - start_time, 2)
    add_log(f"HOÀN THÀNH: Đã tính toán xong cho {len(output_rows)} cells ({total_sites} sites) trong {elapsed_time} giây.")

    return df_output, "\n".join(logs), elapsed_time
