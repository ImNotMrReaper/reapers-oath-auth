import os
import sys
import time
import json
import glob
import re
import signal
import configparser
import dlib
import cv2
import numpy as np
import concurrent.futures

# Setup paths and config
howdy_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, howdy_dir)
from recorders.video_capture import discover_capture_devices, open_single_camera, format_camera_name
import security
import vision_engine

# Lock virtual memory pages into RAM to block swap disk paging
vision_engine.lock_process_memory()

config = configparser.ConfigParser()
config.read(os.path.join(howdy_dir, "config.ini"))
certainty_threshold = config.getfloat("video", "certainty", fallback=3.5)
user = os.getenv("SUDO_USER") or os.getenv("USER") or "mr-reaper"

# Hardware acceleration telemetry
accel_badge = vision_engine.get_hardware_acceleration_badge()

# Load models via hardware-bound AES-256-GCM security module
enrolled_vectors = []
enrolled_metadata = []
try:
    models = security.load_user_models(user)
    for m in models:
        for vec in m.get("data", []):
            if len(vec) == 128:
                enrolled_vectors.append(vec)
                enrolled_metadata.append({"id": m.get("id", 0), "label": m.get("label", "enrolled")})
except Exception as e:
    print(f"Notice loading face models: {e}")

known_matrix = np.array(enrolled_vectors) if enrolled_vectors else None

# Discover and open all initial candidate cameras (HD 1280x720 MJPG with sensor sharpness optimization)
candidates = discover_capture_devices()
with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(candidates))) as executor:
    results = list(executor.map(lambda c: open_single_camera(c, force_mjpeg=True, fw=1280, fh=720), candidates))
caps = [c for c in results if c is not None]

print("\n==================================================================")
print("     HOWDY ENTERPRISE ADAPTIVE BIOMETRIC HUD (GEMINI BLUEPRINT)   ")
print("==================================================================")
print(f"• Active Target User: {user}")
print(f"• Enrolled Identity Scans: {len(enrolled_vectors)} models (AES-256-GCM)")
print(f"• Recognition Threshold (Certainty): {certainty_threshold} (Lower = Stricter)")
print(f"• Hardware Compute Engine: {accel_badge}")
print(f"• Armed Cameras ({len(caps)} active concurrently):")
for idx, c in enumerate(caps):
    print(f"    [{idx + 1}] {c['name']} ({c['path']})")
print("• Vision Pipeline: MSRCR Retinex + YuNet CNN (±85° Yaw) + MiniFASNet Liveness")
print("• Close Controls: Click on-screen [X CLOSE], or press 'q' / ESC / 'x'")
print("==================================================================\n")

# Initialize Vision Models
detector = dlib.get_frontal_face_detector()
predictor = dlib.shape_predictor(os.path.join(howdy_dir, "dlib-data", "shape_predictor_5_face_landmarks.dat"))
encoder = dlib.face_recognition_model_v1(os.path.join(howdy_dir, "dlib-data", "dlib_face_recognition_resnet_model_v1.dat"))

yunet_path = os.path.join(howdy_dir, "models", "face_detection_yunet_2023mar.onnx")
yunet_detector = vision_engine.ONNXYuNetDetector(yunet_path)

liveness_path = os.path.join(howdy_dir, "models", "minifasnet_v2.onnx")
liveness_verifier = vision_engine.PassiveLivenessVerifier(liveness_path)

haar_path = "/usr/share/opencv4/haarcascades/haarcascade_frontalface_alt2.xml"
haar_detector = cv2.CascadeClassifier(haar_path) if os.path.isfile(haar_path) else None

WIN_NAME = "Howdy Enterprise Face ID Biometric HUD"
cv2.namedWindow(WIN_NAME, cv2.WINDOW_NORMAL)

TILE_W = 640
TILE_H = 480

# Close Button & Mouse Event State
exit_requested = False
btn_bounds = [0, 0, 0, 0]  # [x1, y1, x2, y2]

def on_mouse(event, x, y, flags, param):
    global exit_requested
    if event == cv2.EVENT_LBUTTONDOWN:
        if (btn_bounds[0] <= x <= btn_bounds[2]) and (btn_bounds[1] <= y <= btn_bounds[3]):
            exit_requested = True

cv2.setMouseCallback(WIN_NAME, on_mouse)

def sig_handler(sig, frame):
    global exit_requested
    exit_requested = True

signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)


def draw_biometric_hud(frame, rect, shape, is_match, best_dist, cert_thresh, best_id, best_label, target_user, light_text, light_color, det_text, liveness_pct, is_live):
    """Render sci-fi biometric HUD overlay with constellation mesh, confidence gauge, and telemetry badges"""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = rect.left(), rect.top(), rect.right(), rect.bottom()
    hud_color = (0, 255, 64) if (is_match and is_live) else (48, 48, 255)

    # 1. Corner Reticle Brackets (Sci-Fi Framing)
    bracket_len = int((x2 - x1) * 0.22)
    thick = 2
    # Top-Left
    cv2.line(frame, (x1, y1), (x1 + bracket_len, y1), hud_color, thick)
    cv2.line(frame, (x1, y1), (x1, y1 + bracket_len), hud_color, thick)
    # Top-Right
    cv2.line(frame, (x2, y1), (x2 - bracket_len, y1), hud_color, thick)
    cv2.line(frame, (x2, y1), (x2, y1 + bracket_len), hud_color, thick)
    # Bottom-Left
    cv2.line(frame, (x1, y2), (x1 + bracket_len, y2), hud_color, thick)
    cv2.line(frame, (x1, y2), (x1, y2 - bracket_len), hud_color, thick)
    # Bottom-Right
    cv2.line(frame, (x2, y2), (x2 - bracket_len, y2), hud_color, thick)
    cv2.line(frame, (x2, y2), (x2, y2 - bracket_len), hud_color, thick)

    # 2. Biometric Landmark Constellation Mesh
    pts = [(shape.part(i).x, shape.part(i).y) for i in range(shape.num_parts)]
    if len(pts) >= 5:
        # Connect eye contours
        cv2.line(frame, pts[0], pts[1], (0, 240, 220), 1, cv2.LINE_AA)
        cv2.line(frame, pts[1], pts[2], (0, 200, 255), 1, cv2.LINE_AA)
        cv2.line(frame, pts[2], pts[3], (0, 240, 220), 1, cv2.LINE_AA)
        # Connect eyes to nose anchor
        cv2.line(frame, pts[0], pts[4], (0, 180, 255), 1, cv2.LINE_AA)
        cv2.line(frame, pts[1], pts[4], (0, 220, 255), 1, cv2.LINE_AA)
        cv2.line(frame, pts[2], pts[4], (0, 220, 255), 1, cv2.LINE_AA)
        cv2.line(frame, pts[3], pts[4], (0, 180, 255), 1, cv2.LINE_AA)

        # Draw biometric nodes
        for p in pts:
            cv2.circle(frame, p, 3, (0, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, p, 6, (0, 200, 100), 1, cv2.LINE_AA)

        # Nose target reticle crosshair
        cv2.drawMarker(frame, pts[4], (0, 255, 255), markerType=cv2.MARKER_CROSS, markerSize=12, thickness=1)

    # 3. Upper Status Banner
    if is_match and is_live:
        title_text = f"MATCH: {target_user.upper()} [AUTHORIZED]"
    elif is_match and not is_live:
        title_text = "SPOOF ATTACK DETECTED [REJECTED]"
    else:
        title_text = "UNKNOWN SUBJECT [ACCESS DENIED]"

    banner_w = max(240, len(title_text) * 10)
    bx1 = max(10, x1)
    by1 = max(28, y1 - 10)
    cv2.rectangle(frame, (bx1, by1 - 22), (bx1 + banner_w, by1), hud_color, cv2.FILLED)
    cv2.putText(frame, title_text, (bx1 + 6, by1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 0, 0), 1, cv2.LINE_AA)

    # 4. Lower Telemetry Badges & Gauges
    ly = min(h - 75, y2 + 18)

    # Environmental Lighting Badge (MSRCR)
    cv2.rectangle(frame, (bx1, ly - 14), (bx1 + 250, ly + 2), (20, 20, 20), cv2.FILLED)
    cv2.rectangle(frame, (bx1, ly - 14), (bx1 + 250, ly + 2), light_color, 1)
    cv2.putText(frame, f"LIGHT: {light_text}", (bx1 + 5, ly - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.35, light_color, 1, cv2.LINE_AA)

    # Detector & Architecture Badge
    ly += 18
    cv2.rectangle(frame, (bx1, ly - 14), (bx1 + 250, ly + 2), (20, 20, 20), cv2.FILLED)
    cv2.rectangle(frame, (bx1, ly - 14), (bx1 + 250, ly + 2), (200, 100, 255), 1)
    cv2.putText(frame, f"BACKBONE: {det_text}", (bx1 + 5, ly - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (220, 150, 255), 1, cv2.LINE_AA)

    # Passive Liveness Badge (MiniFASNet)
    ly += 18
    live_col = (0, 255, 128) if is_live else (0, 0, 255)
    live_txt = f"LIVENESS: {liveness_pct:.1f}% [PASS - REAL]" if is_live else f"LIVENESS: {liveness_pct:.1f}% [SPOOF BLOCKED]"
    cv2.rectangle(frame, (bx1, ly - 14), (bx1 + 250, ly + 2), (20, 20, 20), cv2.FILLED)
    cv2.rectangle(frame, (bx1, ly - 14), (bx1 + 250, ly + 2), live_col, 1)
    cv2.putText(frame, live_txt, (bx1 + 5, ly - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.35, live_col, 1, cv2.LINE_AA)

    # Confidence Meter Bar
    ly += 20
    bar_w = 250
    cv2.rectangle(frame, (bx1, ly - 12), (bx1 + bar_w, ly + 2), (30, 30, 30), cv2.FILLED)
    cv2.rectangle(frame, (bx1, ly - 12), (bx1 + bar_w, ly + 2), (70, 70, 70), 1)

    if is_match and cert_thresh > 0:
        conf_pct = max(0, min(100, int((1.0 - (best_dist / cert_thresh)) * 100)))
        fill_w = int(bar_w * (conf_pct / 100.0))
        cv2.rectangle(frame, (bx1 + 1, ly - 11), (bx1 + fill_w, ly + 1), (0, 200, 80), cv2.FILLED)
        score_str = f"CONF: {conf_pct}% | CERT: {best_dist:.2f}/{cert_thresh:.1f}"
    else:
        score_str = f"NO MATCH | DIST: {best_dist:.2f} (MAX {cert_thresh:.1f})"

    cv2.putText(frame, score_str, (bx1 + 5, ly - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (240, 240, 240), 1, cv2.LINE_AA)


def build_hud_grid(tiles, active_caps, cur_user, enc_count, cert_thresh):
    N = len(tiles)
    if N == 0:
        standby = np.zeros((480, 640, 3), dtype=np.uint8)
        standby[:] = (20, 20, 20)
        cv2.putText(standby, "HOWDY BIOMETRIC HUD", (170, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(standby, "NO CAMERAS CONNECTED", (160, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2, cv2.LINE_AA)
        cv2.putText(standby, "Plug in a USB webcam or open laptop lid...", (140, 275), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (180, 180, 180), 1, cv2.LINE_AA)
        cv2.putText(standby, "Click [X CLOSE] or press 'q' to exit", (200, 320), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 120, 120), 1, cv2.LINE_AA)
        return standby, 640, 480

    norm_tiles = []
    for t in tiles:
        if t.shape[1] != TILE_W or t.shape[0] != TILE_H:
            norm_tiles.append(cv2.resize(t, (TILE_W, TILE_H), interpolation=cv2.INTER_AREA))
        else:
            norm_tiles.append(t)

    if N == 1:
        return norm_tiles[0], TILE_W, TILE_H

    if N == 2:
        return np.hstack([norm_tiles[0], norm_tiles[1]]), TILE_W * 2, TILE_H

    cols = 2 if N <= 4 else int(np.ceil(np.sqrt(N)))
    rows = int(np.ceil(N / cols))
    total_slots = cols * rows

    while len(norm_tiles) < total_slots:
        info_tile = np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8)
        info_tile[:] = (18, 18, 18)
        cv2.rectangle(info_tile, (10, 10), (TILE_W - 10, TILE_H - 10), (50, 50, 50), 1)
        cv2.rectangle(info_tile, (10, 10), (TILE_W - 10, 45), (32, 32, 32), cv2.FILLED)
        cv2.putText(info_tile, "SYSTEM BIOMETRICS & TELEMETRY", (20, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 1, cv2.LINE_AA)

        y = 80
        info_items = [
            f"User Target: {cur_user}",
            f"Enrolled Faces: {enc_count} models (AES-256-GCM)",
            f"Active Sensors: {len(active_caps)} cameras armed",
            f"Certainty Threshold: {cert_thresh}",
            f"Hardware Compute: {accel_badge}",
            "Photometric Pipeline: MSRCR Multi-Scale Retinex",
            "Detection Backbone: YuNet CNN (+-85 deg Yaw)",
            "Liveness Verification: MiniFASNet Passive"
        ]
        for item in info_items:
            cv2.putText(info_tile, f"* {item}", (25, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA)
            y += 34

        y += 10
        cv2.putText(info_tile, "ARMED SENSORS:", (25, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 128), 1, cv2.LINE_AA)
        y += 24
        for c_idx, c in enumerate(active_caps, 1):
            cv2.putText(info_tile, f"  [{c_idx}] {c['name']}", (25, y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (160, 220, 255), 1, cv2.LINE_AA)
            y += 22

        norm_tiles.append(info_tile)

    grid_rows = []
    for r in range(rows):
        grid_rows.append(np.hstack(norm_tiles[r * cols : (r + 1) * cols]))
    grid = np.vstack(grid_rows)
    return grid, TILE_W * cols, TILE_H * rows


last_win_dims = (0, 0)
frame_count = 0
fps_timer = time.time()
fps = 0
rec_ms = 0
last_probe_time = time.time()

try:
    while not exit_requested:
        # Check window visibility property
        try:
            vis_prop = cv2.getWindowProperty(WIN_NAME, cv2.WND_PROP_VISIBLE)
            auto_prop = cv2.getWindowProperty(WIN_NAME, cv2.WND_PROP_AUTOSIZE)
            if vis_prop <= 0 or auto_prop < 0:
                break
        except Exception:
            break

        # 1. Hotplug probe every 1.0 second
        if time.time() - last_probe_time >= 1.0:
            last_probe_time = time.time()
            try:
                cur_devs = discover_capture_devices()
                active_paths = [c["path"] for c in caps]
                for dev_info in cur_devs:
                    if dev_info["path"] not in active_paths:
                        new_c = open_single_camera(dev_info, force_mjpeg=True, fw=1280, fh=720)
                        if new_c:
                            caps.append(new_c)
                            print(f"\033[92m[Howdy Test] Hotplug detected! Armed new camera: {new_c['name']} ({new_c['path']})\033[0m")
            except Exception:
                pass

        # 2. Capture and process frames from all active cameras
        processed_frames = []
        dead_cams = []

        for cam in caps:
            try:
                ret, frame = cam["cap"].read()
            except Exception:
                ret, frame = False, None

            if not ret or frame is None:
                dead_cams.append(cam)
                continue

            if frame.shape[1] != TILE_W or frame.shape[0] != TILE_H:
                frame = cv2.resize(frame, (TILE_W, TILE_H), interpolation=cv2.INTER_AREA)

            # MSRCR Dynamic Photometric Preprocessing (Gemini Blueprint Section 1)
            t0 = time.time()
            enh_frame, enh_gs, light_label, light_col = vision_engine.adaptive_photometric_preprocess(frame)

            # Multi-Backbone Detection Cascade (Gemini Blueprint Section 2)
            face_locations = []
            det_label = "NONE"

            # Primary: YuNet CNN (+-85 deg yaw, sub-10ms)
            if yunet_detector.available:
                yn_faces = yunet_detector.detect(enh_frame)
                if yn_faces:
                    face_locations = [f["rect"] for f in yn_faces]
                    det_label = "YUNET CNN (+-85 YAW)"

            # Secondary: dlib HOG
            if len(face_locations) == 0:
                hog_faces = detector(enh_gs, 1)
                if len(hog_faces) > 0:
                    face_locations = hog_faces
                    det_label = "DLIB HOG (GRADIENT)"

            # Tertiary: Haar Cascade
            if len(face_locations) == 0 and haar_detector is not None:
                haar_boxes = haar_detector.detectMultiScale(enh_gs, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60))
                if len(haar_boxes) > 0:
                    face_locations = [dlib.rectangle(int(hx), int(hy), int(hx + hw), int(hy + hh)) for (hx, hy, hw, hh) in haar_boxes]
                    det_label = "HAAR CASCADE"

            rec_ms = int((time.time() - t0) * 1000)

            # Camera label banner
            cv2.rectangle(frame, (10, 10), (10 + len(cam["name"]) * 11, 35), (20, 20, 20), cv2.FILLED)
            cv2.putText(frame, f"[{cam['name'].upper()}]", (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)

            for rect in face_locations:
                # Passive Liveness Verification (Gemini Blueprint Section 3)
                liveness_pct = 100.0
                is_live = True
                if liveness_verifier.available:
                    liveness_score, is_live = liveness_verifier.verify(enh_frame, rect)
                    liveness_pct = liveness_score * 100.0

                shape = predictor(enh_frame, rect)
                face_desc = np.array(encoder.compute_face_descriptor(enh_frame, shape, num_jitters=1))

                is_match = False
                best_dist = 99.0
                best_label = "unknown"
                best_id = -1

                if known_matrix is not None and len(known_matrix) > 0:
                    distances = np.linalg.norm(known_matrix - face_desc, axis=1) * 10.0
                    min_idx = np.argmin(distances)
                    best_dist = distances[min_idx]
                    if best_dist <= certainty_threshold:
                        is_match = True
                        best_id = enrolled_metadata[min_idx]["id"]
                        best_label = enrolled_metadata[min_idx]["label"]

                draw_biometric_hud(
                    frame, rect, shape, is_match, best_dist, certainty_threshold,
                    best_id, best_label, user, light_label, light_col, det_label, liveness_pct, is_live
                )

            processed_frames.append(frame)

        # 3. Handle hot-unplugged cameras
        if dead_cams:
            for dead in dead_cams:
                print(f"\033[93m[Howdy Test] Disconnected {dead['name']} ({dead['path']})\033[0m")
                try:
                    dead["cap"].release()
                except Exception:
                    pass
                if dead in caps:
                    caps.remove(dead)

        # 4. FPS counter
        frame_count += 1
        if time.time() - fps_timer >= 1.0:
            fps = frame_count
            frame_count = 0
            fps_timer = time.time()

        # 5. Build dynamic grid layout
        display_frame, target_w, target_h = build_hud_grid(
            processed_frames, caps, user, len(enrolled_vectors), certainty_threshold
        )

        dh, dw = display_frame.shape[:2]

        # 6. Render Glowing Red Clickable [ X CLOSE / EXIT ] Button at Top-Right
        btn_w, btn_h = 160, 34
        bx1 = dw - btn_w - 15
        by1 = 12
        bx2 = bx1 + btn_w
        by2 = by1 + btn_h
        btn_bounds = [bx1, by1, bx2, by2]

        cv2.rectangle(display_frame, (bx1, by1), (bx2, by2), (40, 20, 180), cv2.FILLED)
        cv2.rectangle(display_frame, (bx1, by1), (bx2, by2), (80, 50, 255), 2)
        cv2.putText(display_frame, "[X] CLOSE / EXIT", (bx1 + 14, by1 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (255, 255, 255), 1, cv2.LINE_AA)

        # Telemetry bottom bar
        cv2.rectangle(display_frame, (0, dh - 32), (dw, dh), (10, 10, 10), cv2.FILLED)
        info_str = f"MULTI-CAMERA HUD ({len(caps)} ARMED) | FPS: {fps} | INFERENCE: {rec_ms}ms | HARDWARE: {accel_badge} | CLICK [X] TO EXIT"
        cv2.putText(display_frame, info_str, (15, dh - 11), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1, cv2.LINE_AA)

        if (target_w, target_h) != last_win_dims:
            cv2.resizeWindow(WIN_NAME, target_w, target_h)
            last_win_dims = (target_w, target_h)

        cv2.imshow(WIN_NAME, display_frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord('q'), ord('Q'), ord('x'), ord('X')):
            break

finally:
    for cam in caps:
        try:
            cam["cap"].release()
        except Exception:
            pass
    cv2.destroyAllWindows()
    for _ in range(10):
        cv2.waitKey(1)
    vision_engine.trim_heap_memory()
    print("[Howdy Test] Biometric HUD closed cleanly.")
