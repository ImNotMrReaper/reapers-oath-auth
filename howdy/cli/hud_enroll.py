#!/usr/bin/env python3
# ==============================================================================
# HOWDY HIGH-PERFORMANCE LIVE HUD BIOMETRIC ENROLLMENT ENGINE
# Renders a real-time Sci-Fi Biometric HUD at 30+ FPS while continuously capturing,
# quality-filtering, and enrolling high-precision facial descriptors across
# multiple cameras, angles, distances, and lighting conditions.
# Storage: Machine-Bound AES-256-GCM AEAD + XZ (LZMA2) Compressed Vault
# ==============================================================================

import os
import sys
import time
import json
import glob
import re
import signal
import configparser
import argparse
import threading
import queue
import subprocess
import dlib
import cv2
import numpy as np

howdy_dir = "/lib/security/howdy"
if not os.path.isdir(howdy_dir):
    howdy_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, howdy_dir)
from recorders.video_capture import discover_capture_devices, calibrate_camera_hardware
import security
import vision_engine

vision_engine.lock_process_memory()

# CLI Argument Parsing
parser = argparse.ArgumentParser(description="Howdy High-Performance Interactive Biometric HUD Enrollment")
parser.add_argument("--target", "-t", type=int, default=1000, help="Target total enrolled models in vault (default: 1000)")
parser.add_argument("--user", "-u", type=str, default=None, help="Target user for enrollment")
args, _ = parser.parse_known_args()

user = args.user or os.getenv("SUDO_USER") or os.getenv("USER") or "mr-reaper"
TARGET_TOTAL_MODELS = max(10, args.target)

config = configparser.ConfigParser()
config.read(os.path.join(howdy_dir, "config.ini"))
certainty_threshold = config.getfloat("video", "certainty", fallback=3.5)

# Hardware acceleration telemetry
accel_badge = vision_engine.get_hardware_acceleration_badge()

# Load existing models
existing_models = security.load_user_models(user)
enrolled_vectors = []
for m in existing_models:
    for vec in m.get("data", []):
        if len(vec) == 128:
            enrolled_vectors.append(vec)

known_matrix = np.array(enrolled_vectors) if enrolled_vectors else None

needed_new = max(10, TARGET_TOTAL_MODELS - len(existing_models))


# -----------------------------------------------------------------------------
# Zero-Latency Background Threaded Camera Reader
# -----------------------------------------------------------------------------
class ThreadedCamera:
    """Non-blocking threaded camera reader that continuously polls frames in background"""
    def __init__(self, dev_info, fw=1280, fh=720, force_mjpeg=True):
        self.dev_info = dev_info
        self.path = dev_info["path"]
        self.name = dev_info["name"]
        self.running = False
        self.frame = None
        self.lock = threading.Lock()
        self.thread = None
        self.cap = None
        self.fw = fw
        self.fh = fh
        self.force_mjpeg = force_mjpeg
        self.open()

    def open(self):
        # Auto-calibrate hardware sensor controls dynamically based on device capabilities
        calibrate_camera_hardware(self.path, self.name)

        self.cap = cv2.VideoCapture(self.path, cv2.CAP_V4L2)
        if self.force_mjpeg:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        if self.fw > 0:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.fw)
        if self.fh > 0:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.fh)
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        if self.cap.isOpened() and self.cap.grab():
            ret, frame = self.cap.retrieve()
            if ret and frame is not None:
                self.frame = frame
                self.running = True
                self.thread = threading.Thread(target=self._capture_loop, daemon=True)
                self.thread.start()
                return True
        return False

    def _capture_loop(self):
        while self.running and self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret and frame is not None:
                with self.lock:
                    self.frame = frame
            else:
                time.sleep(0.005)

    def read(self):
        with self.lock:
            if self.frame is not None:
                return True, self.frame.copy()
            return False, None

    def release(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.3)
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass


# Discover and initialize all candidate cameras concurrently
candidates = discover_capture_devices()
caps = []
for c in candidates:
    tcam = ThreadedCamera(c, fw=1280, fh=720, force_mjpeg=True)
    if tcam.running:
        caps.append(tcam)

if not caps:
    print("[Error] No cameras available for enrollment.", file=sys.stderr)
    sys.exit(1)

target_per_camera = max(1, needed_new // len(caps))

print("\n==================================================================")
print("     HOWDY LIVE HUD INTERACTIVE BIOMETRIC ENROLLMENT ENGINE       ")
print("==================================================================")
print(f"• Active Target User: {user}")
print(f"• Initial Enrolled Vault: {len(existing_models)} models")
print(f"• Target Total Vault: {TARGET_TOTAL_MODELS} models (+{needed_new} new scans)")
print(f"• Target per Camera: {target_per_camera} scans/camera")
print(f"• Storage Format: Machine-Bound AES-256-GCM AEAD + XZ (LZMA2)")
print(f"• Sensor Calibration: Hardware Sharpness=7, Native 1280x720 MJPG")
print(f"• Compute Hardware: {accel_badge}")
print(f"• Armed Cameras ({len(caps)} active concurrently):")
for idx, c in enumerate(caps):
    print(f"    [{idx + 1}] {c.name} ({c.path})")
print("• Live Visual HUD: Active on display")
print("• Controls: Move head across varied angles, tilts, distances")
print("• Finish: Click [X CLOSE / FINISH] or press 'q' / ESC at any time")
print("==================================================================\n")

# Initialize models
detector = dlib.get_frontal_face_detector()
predictor = dlib.shape_predictor(os.path.join(howdy_dir, "dlib-data", "shape_predictor_5_face_landmarks.dat"))
encoder = dlib.face_recognition_model_v1(os.path.join(howdy_dir, "dlib-data", "dlib_face_recognition_resnet_model_v1.dat"))

yunet_path = os.path.join(howdy_dir, "models", "face_detection_yunet_2023mar.onnx")
yunet_detector = vision_engine.ONNXYuNetDetector(yunet_path)

liveness_path = os.path.join(howdy_dir, "models", "minifasnet_v2.onnx")
liveness_verifier = vision_engine.PassiveLivenessVerifier(liveness_path)

haar_path = "/usr/share/opencv4/haarcascades/haarcascade_frontalface_alt2.xml"
haar_detector = cv2.CascadeClassifier(haar_path) if os.path.isfile(haar_path) else None

# UI Window setup
WIN_NAME = "Howdy Live Biometric HUD & Facial Enrollment (XZ + AES-256-GCM)"
cv2.namedWindow(WIN_NAME, cv2.WINDOW_NORMAL)

TILE_W = 640
TILE_H = 360  # Native 16:9 widescreen tile

exit_requested = False
btn_bounds = [0, 0, 0, 0]


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

# Asynchronous Vector Embedding Worker Thread
enroll_queue = queue.Queue(maxsize=200)
worker_stop = threading.Event()
models_lock = threading.Lock()
new_samples = []
enrolled_ids_assigned = len(existing_models)


def embedding_worker():
    """Background worker that computes 128-d face descriptors and checkpoints to vault"""
    while not worker_stop.is_set() or not enroll_queue.empty():
        try:
            item = enroll_queue.get(timeout=0.1)
        except queue.Empty:
            continue

        enh_frame, shape, cname, sample_idx = item
        try:
            desc = np.array(encoder.compute_face_descriptor(enh_frame, shape, num_jitters=1))
            clean_desc = np.round(desc, 6).tolist()
            cam_clean = "Brio 100" if "Brio" in cname else "Integrated FHD"
            lbl = f"{cam_clean} #{sample_idx + 1}"

            with models_lock:
                new_samples.append({
                    "id": sample_idx,
                    "label": lbl,
                    "data": [clean_desc]
                })
                current_total = len(existing_models) + len(new_samples)

                # Periodic atomic checkpoint every 50 samples
                if len(new_samples) % 50 == 0:
                    security.save_user_models(user, existing_models + new_samples)
                    print(f"  [✓ XZ Checkpoint] Saved {len(new_samples)} samples (Total: {current_total}) [AES-256-GCM + XZ]")
        except Exception as e:
            print(f"[Worker Error] {e}", file=sys.stderr)
        finally:
            enroll_queue.task_done()


worker_thread = threading.Thread(target=embedding_worker, daemon=True)
worker_thread.start()

# Enrollment Tracking State
last_capture_time = {c.name: 0.0 for c in caps}
capture_flash = {c.name: 0.0 for c in caps}
cam_sample_count = {c.name: 0 for c in caps}
enrollment_complete = False

last_verify_time = 0.0
cached_best_dist = 99.0
cached_is_match = False


def draw_biometric_hud(frame, rect, shape, is_match, best_dist, cert_thresh, light_text, light_color, det_text, liveness_pct, is_live, blur_score, flash_active, current_sample_count):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = rect.left(), rect.top(), rect.right(), rect.bottom()
    hud_color = (0, 255, 64) if (is_match and is_live) else (48, 48, 255)

    if flash_active:
        hud_color = (0, 255, 255)  # Cyan/Yellow flash on capture
        cv2.rectangle(frame, (4, 4), (w - 4, h - 4), (0, 255, 255), 3)
        cv2.putText(frame, f"[+ ENROLLED #{current_sample_count}]", (w // 2 - 110, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2, cv2.LINE_AA)

    # 1. Corner Reticle Brackets
    bracket_len = int((x2 - x1) * 0.22)
    thick = 2
    cv2.line(frame, (x1, y1), (x1 + bracket_len, y1), hud_color, thick)
    cv2.line(frame, (x1, y1), (x1, y1 + bracket_len), hud_color, thick)
    cv2.line(frame, (x2, y1), (x2 - bracket_len, y1), hud_color, thick)
    cv2.line(frame, (x2, y1), (x2, y1 + bracket_len), hud_color, thick)
    cv2.line(frame, (x1, y2), (x1 + bracket_len, y2), hud_color, thick)
    cv2.line(frame, (x1, y2), (x1, y2 - bracket_len), hud_color, thick)
    cv2.line(frame, (x2, y2), (x2 - bracket_len, y2), hud_color, thick)
    cv2.line(frame, (x2, y2), (x2, y2 - bracket_len), hud_color, thick)

    # 2. Constellation Mesh
    pts = [(shape.part(i).x, shape.part(i).y) for i in range(shape.num_parts)]
    if len(pts) >= 5:
        cv2.line(frame, pts[0], pts[1], (0, 240, 220), 1, cv2.LINE_AA)
        cv2.line(frame, pts[1], pts[2], (0, 200, 255), 1, cv2.LINE_AA)
        cv2.line(frame, pts[2], pts[3], (0, 240, 220), 1, cv2.LINE_AA)
        cv2.line(frame, pts[0], pts[4], (0, 180, 255), 1, cv2.LINE_AA)
        cv2.line(frame, pts[1], pts[4], (0, 220, 255), 1, cv2.LINE_AA)
        cv2.line(frame, pts[2], pts[4], (0, 220, 255), 1, cv2.LINE_AA)
        cv2.line(frame, pts[3], pts[4], (0, 180, 255), 1, cv2.LINE_AA)
        for p in pts:
            cv2.circle(frame, p, 3, (0, 255, 255), -1, cv2.LINE_AA)
        cv2.drawMarker(frame, pts[4], (0, 255, 255), markerType=cv2.MARKER_CROSS, markerSize=10, thickness=1)

    # 3. Upper Status Banner
    bx1 = max(10, x1)
    by1 = max(24, y1 - 8)
    title_text = f"TARGET: {user.upper()} [TRACKING]"
    banner_w = max(200, len(title_text) * 9)
    cv2.rectangle(frame, (bx1, by1 - 18), (bx1 + banner_w, by1), hud_color, cv2.FILLED)
    cv2.putText(frame, title_text, (bx1 + 5, by1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)

    # 4. Telemetry Badges
    ly = min(h - 65, y2 + 16)
    cv2.rectangle(frame, (bx1, ly - 13), (bx1 + 220, ly + 2), (20, 20, 20), cv2.FILLED)
    cv2.rectangle(frame, (bx1, ly - 13), (bx1 + 220, ly + 2), light_color, 1)
    cv2.putText(frame, f"LIGHT: {light_text}", (bx1 + 5, ly - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.32, light_color, 1, cv2.LINE_AA)

    ly += 16
    cv2.rectangle(frame, (bx1, ly - 13), (bx1 + 220, ly + 2), (20, 20, 20), cv2.FILLED)
    cv2.rectangle(frame, (bx1, ly - 13), (bx1 + 220, ly + 2), (200, 100, 255), 1)
    cv2.putText(frame, f"BACKBONE: {det_text}", (bx1 + 5, ly - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (220, 150, 255), 1, cv2.LINE_AA)

    ly += 16
    sharp_col = (0, 255, 128) if blur_score >= 30.0 else (0, 150, 255)
    cv2.rectangle(frame, (bx1, ly - 13), (bx1 + 220, ly + 2), (20, 20, 20), cv2.FILLED)
    cv2.rectangle(frame, (bx1, ly - 13), (bx1 + 220, ly + 2), sharp_col, 1)
    cv2.putText(frame, f"SHARPNESS: {blur_score:.1f} | LIVENESS: {liveness_pct:.1f}%", (bx1 + 5, ly - 3),
                cv2.FONT_HERSHEY_SIMPLEX, 0.31, sharp_col, 1, cv2.LINE_AA)


last_win_dims = (0, 0)
fps_timer = time.time()
frame_count = 0
fps = 0

try:
    while not exit_requested:
        try:
            vis_prop = cv2.getWindowProperty(WIN_NAME, cv2.WND_PROP_VISIBLE)
            auto_prop = cv2.getWindowProperty(WIN_NAME, cv2.WND_PROP_AUTOSIZE)
            if vis_prop <= 0 or auto_prop < 0:
                break
        except Exception:
            break

        processed_frames = []

        with models_lock:
            total_enrolled = len(existing_models) + len(new_samples)
            captured_count = len(new_samples)

        if total_enrolled >= TARGET_TOTAL_MODELS and not enrollment_complete:
            enrollment_complete = True
            with models_lock:
                security.save_user_models(user, existing_models + new_samples)
            print(f"\n\033[92m[✓] ENROLLMENT COMPLETE: Target of {TARGET_TOTAL_MODELS} reached!\033[0m")
            print(f"\033[92m[✓] Sealed {total_enrolled} face models into AES-256-GCM + XZ vault.\033[0m\n")

        for cam in caps:
            cname = cam.name
            ret, raw_frame = cam.read()

            if not ret or raw_frame is None:
                continue

            # High-speed area downsampling from 1280x720 to tile size
            frame = cv2.resize(raw_frame, (TILE_W, TILE_H), interpolation=cv2.INTER_AREA)

            # MSRCR Dynamic Photometric Preprocessing
            enh_frame, enh_gs, light_label, light_col = vision_engine.adaptive_photometric_preprocess(frame)

            # Multi-Backbone Face Detection Cascade
            face_locations = []
            det_label = "NONE"

            if yunet_detector.available:
                yn_faces = yunet_detector.detect(enh_frame)
                if yn_faces:
                    face_locations = [f["rect"] for f in yn_faces]
                    det_label = "YUNET CNN (+-85 YAW)"

            if len(face_locations) == 0:
                hog_faces = detector(enh_gs, 1)
                if len(hog_faces) > 0:
                    face_locations = hog_faces
                    det_label = "DLIB HOG (GRADIENT)"

            if len(face_locations) == 0 and haar_detector is not None:
                haar_boxes = haar_detector.detectMultiScale(enh_gs, scaleFactor=1.1, minNeighbors=4, minSize=(50, 50))
                if len(haar_boxes) > 0:
                    face_locations = [dlib.rectangle(int(hx), int(hy), int(hx + hw), int(hy + hh)) for (hx, hy, hw, hh) in haar_boxes]
                    det_label = "HAAR CASCADE"

            # Camera label banner
            cam_count = cam_sample_count[cname]
            cv2.rectangle(frame, (10, 8), (10 + len(cname) * 10 + 90, 30), (20, 20, 20), cv2.FILLED)
            cv2.putText(frame, f"[{cname.upper()}] ({cam_count}/{target_per_camera})", (14, 23),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 255), 1, cv2.LINE_AA)

            # Calculate sharpness score (Laplacian variance)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())

            flash_on = (time.time() - capture_flash[cname] < 0.25)

            for rect in face_locations:
                liveness_pct = 100.0
                is_live = True
                if liveness_verifier.available:
                    liveness_score, is_live = liveness_verifier.verify(enh_frame, rect)
                    liveness_pct = liveness_score * 100.0

                shape = predictor(enh_frame, rect)

                # Quality-filtered enrollment gating
                now = time.time()
                can_capture = (
                    not enrollment_complete and
                    captured_count < needed_new and
                    cam_sample_count[cname] < target_per_camera and
                    (now - last_capture_time[cname] >= 0.15) and
                    blur_score >= 25.0 and
                    is_live and
                    enroll_queue.qsize() < 100
                )

                if can_capture:
                    assigned_id = enrolled_ids_assigned
                    enrolled_ids_assigned += 1
                    cam_sample_count[cname] += 1
                    last_capture_time[cname] = now
                    capture_flash[cname] = now
                    flash_on = True

                    # Decoupled async embedding: Enqueue frame + shape
                    enroll_queue.put((enh_frame.copy(), shape, cname, assigned_id))

                    if (assigned_id + 1) % 25 == 0:
                        print(f"  [✓ Enrolled Scan #{assigned_id + 1}/{TARGET_TOTAL_MODELS}] ({cname})")

                # Decoupled distance verification (periodic check every 150ms)
                if now - last_verify_time > 0.15 and known_matrix is not None and len(known_matrix) > 0:
                    try:
                        face_desc_check = np.array(encoder.compute_face_descriptor(enh_frame, shape, num_jitters=1))
                        distances = np.linalg.norm(known_matrix - face_desc_check, axis=1) * 10.0
                        cached_best_dist = float(np.min(distances))
                        cached_is_match = (cached_best_dist <= certainty_threshold)
                        last_verify_time = now
                    except Exception:
                        pass

                draw_biometric_hud(
                    frame, rect, shape, cached_is_match, cached_best_dist, certainty_threshold,
                    light_label, light_col, det_label, liveness_pct, is_live, blur_score,
                    flash_on, total_enrolled
                )

            processed_frames.append(frame)

        # FPS calculation
        frame_count += 1
        if time.time() - fps_timer >= 1.0:
            fps = frame_count
            frame_count = 0
            fps_timer = time.time()

        # Build side-by-side grid
        if len(processed_frames) == 1:
            display_frame = processed_frames[0]
            target_w, target_h = TILE_W, TILE_H
        elif len(processed_frames) >= 2:
            display_frame = np.hstack([processed_frames[0], processed_frames[1]])
            target_w, target_h = TILE_W * 2, TILE_H
        else:
            display_frame = np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8)
            target_w, target_h = TILE_W, TILE_H

        dh, dw = display_frame.shape[:2]

        # Top Enrollment Progress Bar (Height 54)
        top_bar = np.zeros((54, dw, 3), dtype=np.uint8)
        top_bar[:] = (15, 15, 15)
        cv2.line(top_bar, (0, 53), (dw, 53), (40, 40, 40), 1)

        pct = min(1.0, total_enrolled / float(TARGET_TOTAL_MODELS))
        bar_area_w = dw - 340
        prog_w = int(bar_area_w * pct)

        cv2.rectangle(top_bar, (20, 12), (20 + bar_area_w, 32), (30, 30, 30), cv2.FILLED)
        cv2.rectangle(top_bar, (20, 12), (20 + prog_w, 32),
                      (0, 220, 100) if enrollment_complete else (255, 180, 0), cv2.FILLED)
        cv2.rectangle(top_bar, (20, 12), (20 + bar_area_w, 32), (80, 80, 80), 1)

        if not enrollment_complete:
            prog_text = f"ENROLLING VAULT: [ {total_enrolled} / {TARGET_TOTAL_MODELS} ] ({pct*100:.1f}%) | Smoothly tilt head, turn angles, change expressions"
        else:
            prog_text = f"VAULT COMPLETE! {total_enrolled} HIGH-PRECISION MODELS SEALED IN XZ VAULT | Press SPACE for +100"

        cv2.putText(top_bar, prog_text, (26, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (255, 255, 255), 1, cv2.LINE_AA)

        # Top-Right [X CLOSE / FINISH] button
        btn_w, btn_h = 160, 32
        bx1 = dw - btn_w - 15
        by1 = 11
        bx2 = bx1 + btn_w
        by2 = by1 + btn_h
        btn_bounds = [bx1, by1, bx2, by2]

        cv2.rectangle(top_bar, (bx1, by1), (bx2, by2), (40, 20, 180), cv2.FILLED)
        cv2.rectangle(top_bar, (bx1, by1), (bx2, by2), (80, 50, 255), 2)
        cv2.putText(top_bar, "[X] CLOSE / FINISH", (bx1 + 10, by1 + 21), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1, cv2.LINE_AA)

        # Bottom Bar (Height 34)
        bot_bar = np.zeros((34, dw, 3), dtype=np.uint8)
        bot_bar[:] = (10, 10, 10)
        cv2.line(bot_bar, (0, 0), (dw, 0), (40, 40, 40), 1)
        b_str = f"LIVE MULTI-CAMERA HUD ({len(caps)} SENSORS) | FPS: {fps} | CIPHER: AES-256-GCM + XZ (LZMA2) | COMPUTE: {accel_badge}"
        cv2.putText(bot_bar, b_str, (15, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (200, 200, 200), 1, cv2.LINE_AA)

        # Assemble full composite window
        full_window = np.vstack([top_bar, display_frame, bot_bar])
        f_h, f_w = full_window.shape[:2]

        if (f_w, f_h) != last_win_dims:
            cv2.resizeWindow(WIN_NAME, f_w, f_h)
            last_win_dims = (f_w, f_h)

        cv2.imshow(WIN_NAME, full_window)

        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord('q'), ord('Q'), ord('x'), ord('X')):
            break
        elif key == 32 and enrollment_complete:
            TARGET_TOTAL_MODELS += 100
            needed_new = TARGET_TOTAL_MODELS - total_enrolled
            target_per_camera = max(1, needed_new // len(caps))
            enrollment_complete = False
            print(f"\n>>> Extending target: Enrolling 100 more scans (New Target: {TARGET_TOTAL_MODELS})...")

finally:
    print("\n[Howdy Scanner] Flushing enrollment queue and releasing hardware handles...")
    worker_stop.set()
    enroll_queue.join()
    worker_thread.join(timeout=2.0)

    for cam in caps:
        try:
            cam.release()
        except Exception:
            pass

    cv2.destroyAllWindows()
    for _ in range(10):
        cv2.waitKey(1)

    # Final atomic vault save
    with models_lock:
        all_models = existing_models + new_samples
        if len(new_samples) > 0:
            security.save_user_models(user, all_models)
            model_path = os.path.join(howdy_dir, "models", f"{user}.dat")
            file_size_kb = os.path.getsize(model_path) / 1024.0 if os.path.exists(model_path) else 0.0
            print(f"\n\033[92m==================================================================")
            print(f"      BIOMETRIC ENROLLMENT VAULT SUCCESSFULLY SEALED             ")
            print(f"==================================================================")
            print(f"• Target User: {user}")
            print(f"• Total Models in Vault: {len(all_models)} (Enrolled +{len(new_samples)} new scans)")
            print(f"• Cryptographic Cipher: AES-256-GCM AEAD (Machine-Bound HKDF-SHA256)")
            print(f"• Compression Algorithm: XZ (LZMA2 Preset 6)")
            print(f"• Encrypted Vault File: {model_path} ({file_size_kb:.1f} KB on disk)")
            print(f"==================================================================\033[0m\n")

    vision_engine.trim_heap_memory()
