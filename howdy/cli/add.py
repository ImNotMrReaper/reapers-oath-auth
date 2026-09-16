# Save the face of the user in encoded form with Multi-Camera Depth Support & AES-256-GCM Encryption
import time
import os
import sys
import json
import configparser
import builtins
import numpy as np
import cv2

path = os.path.abspath(__file__ + "/..")
howdy_dir = os.path.realpath(path + "/..")
sys.path.insert(0, howdy_dir)
import security
from recorders.video_capture import VideoCapture

try:
	import dlib
except ImportError as err:
	print(err)
	print("\nCan't import the dlib module, check pip3 show dlib")
	sys.exit(1)

if not os.path.isfile(howdy_dir + "/dlib-data/shape_predictor_5_face_landmarks.dat"):
	print("Data files missing in dlib-data, please run install.sh")
	sys.exit(1)

config = configparser.ConfigParser()
config.read(howdy_dir + "/config.ini")

use_cnn = config.getboolean("core", "use_cnn", fallback=False)
if use_cnn:
	face_detector = dlib.cnn_face_detection_model_v1(howdy_dir + "/dlib-data/mmod_human_face_detector.dat")
else:
	face_detector = dlib.get_frontal_face_detector()

pose_predictor = dlib.shape_predictor(howdy_dir + "/dlib-data/shape_predictor_5_face_landmarks.dat")
face_encoder = dlib.face_recognition_model_v1(howdy_dir + "/dlib-data/dlib_face_recognition_resnet_model_v1.dat")

user = builtins.howdy_user
# Load existing models through hardware-bound AES-256-GCM decryption
encodings = security.load_user_models(user)

print("Adding face model for the user " + user)

# Determine default label
default_label = "Model #" + str(len(encodings) + 1) if encodings else "Initial model"

if builtins.howdy_args.y:
	label = default_label
	print('Using default label "%s" because of -y flag' % (label, ))
else:
	label_in = input(f"Enter a label for this new model [{default_label}] (max 24 characters): ")
	label = label_in[:24] if label_in != "" else default_label

# Initialize multi-camera capture
video_capture = VideoCapture(config)
armed_cams = video_capture.active_cameras
print(f"\n[Multi-Angle Capture] Armed {len(armed_cams)} camera(s) concurrently:")
for idx, c in enumerate(armed_cams, 1):
	print(f"  Camera {idx}: {c['name']} ({c['path']})")

print("\nPlease look toward your screens/cameras naturally...")
time.sleep(1.5)

captured_by_camera = {}
frames = 0
dark_threshold = config.getfloat("video", "dark_threshold", fallback=50.0)
clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

# Capture frames across all cameras until each camera has recorded a face or timeout
max_frames = 40 * max(1, len(armed_cams))
while frames < max_frames and video_capture.active_cameras and any(c["name"] not in captured_by_camera for c in video_capture.active_cameras):
	frames += 1
	frame, gsframe = video_capture.read_frame()
	cam_name = video_capture.last_camera_name

	if cam_name in captured_by_camera:
		continue

	gsframe_clahe = clahe.apply(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
	hist = cv2.calcHist([gsframe_clahe], [0], None, [8], [0, 256])
	hist_total = np.sum(hist)
	if hist_total == 0 or (hist[0] / hist_total * 100) > dark_threshold:
		continue

	face_locations = face_detector(gsframe_clahe, 1)
	if len(face_locations) == 1:
		fl = face_locations[0]
		if use_cnn:
			fl = fl.rect
		shape = pose_predictor(frame, fl)
		desc = np.array(face_encoder.compute_face_descriptor(frame, shape, 1))
		captured_by_camera[cam_name] = desc
		print(f"  ✓ Captured face angle from {cam_name}")

video_capture.release()

if not captured_by_camera:
	print("No face detected on any active camera, aborting.")
	sys.exit(1)

# Add all captured angles to user models
next_id = len(encodings)
for cam_name, desc in captured_by_camera.items():
	cam_label = f"{label} [{cam_name}]" if len(armed_cams) > 1 else label
	encodings.append({
		"time": int(time.time()),
		"label": cam_label[:40],
		"id": next_id,
		"data": [desc.tolist()]
	})
	next_id += 1

# Encrypt and save to disk via AES-256-GCM
security.save_user_models(user, encodings)

print(f"\n\033[92mScan complete! Enrolled {len(captured_by_camera)} multi-angle model(s) for {user} (AES-256-GCM Encrypted).\033[0m")
print(f"Total active models: {len(encodings)}\n")
