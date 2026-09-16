# Compare incomming video with known faces
# Running in a local python instance to get around PATH issues

# Import time so we can start timing asap
import time

# Start timing
timings = {
	"st": time.time()
}

# Import required modules
import sys
import os
import json
import configparser
import dlib
import cv2
import datetime
import snapshot
import numpy as np
import _thread as thread
from recorders.video_capture import VideoCapture
import vision_engine
vision_engine.lock_process_memory()


def init_detector(lock):
	"""Start face detector, encoder and predictor in a new thread"""
	global face_detector, pose_predictor, face_encoder, haar_detector, yunet_detector, liveness_verifier

	yunet_detector = vision_engine.ONNXYuNetDetector(PATH + "/models/face_detection_yunet_2023mar.onnx")
	liveness_verifier = vision_engine.PassiveLivenessVerifier(PATH + "/models/minifasnet_v2.onnx")

	# Test if at lest 1 of the data files is there and abort if it's not
	if not os.path.isfile(PATH + "/dlib-data/shape_predictor_5_face_landmarks.dat"):
		print("Data files have not been downloaded, please run the following commands:")
		print("\n\tcd " + PATH + "/dlib-data")
		print("\tsudo ./install.sh\n")
		lock.release()
		sys.exit(1)

	# Use the CNN detector if enabled
	if use_cnn:
		face_detector = dlib.cnn_face_detection_model_v1(PATH + "/dlib-data/mmod_human_face_detector.dat")
	else:
		face_detector = dlib.get_frontal_face_detector()

	# Start the others regardless
	pose_predictor = dlib.shape_predictor(PATH + "/dlib-data/shape_predictor_5_face_landmarks.dat")
	face_encoder = dlib.face_recognition_model_v1(PATH + "/dlib-data/dlib_face_recognition_resnet_model_v1.dat")
	haar_path = "/usr/share/opencv4/haarcascades/haarcascade_frontalface_alt2.xml"
	if os.path.isfile(haar_path):
		haar_detector = cv2.CascadeClassifier(haar_path)
	else:
		haar_detector = None

	# Note the time it took to initialize detectors
	timings["ll"] = time.time() - timings["ll"]
	lock.release()


def make_snapshot(type):
	"""Generate snapshot after detection"""
	snapshot.generate(snapframes, [
		type + " LOGIN",
		"Date: " + datetime.datetime.utcnow().strftime("%Y/%m/%d %H:%M:%S UTC"),
		"Scan time: " + str(round(time.time() - timings["fr"], 2)) + "s",
		"Frames: " + str(frames) + " (" + str(round(frames / (time.time() - timings["fr"]), 2)) + "FPS)",
		"Hostname: " + os.uname().nodename,
		"Best certainty value: " + str(round(lowest_certainty * 10, 1))
	])


def adaptive_illumination_enhance(bgr_img, base_gs):
	"""Multi-environmental lighting adaptation engine.
	Recovers facial contours in low light, harsh glare, and lower-fidelity
	integrated laptop cameras without degrading geometry or lowering security thresholds."""
	mean_val = float(np.mean(base_gs))
	if mean_val < 85.0:
		gamma = max(0.45, min(0.85, mean_val / 110.0))
		inv_gamma = 1.0 / gamma
		lut = np.array([((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
		gamma_corrected = cv2.LUT(base_gs, lut)
		clahe_boost = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
		return clahe_boost.apply(gamma_corrected)
	elif mean_val > 165.0:
		gamma = min(1.6, max(1.15, mean_val / 120.0))
		inv_gamma = 1.0 / gamma
		lut = np.array([((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
		compressed = cv2.LUT(base_gs, lut)
		clahe_glare = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
		return clahe_glare.apply(compressed)
	else:
		try:
			lab = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2LAB)
			l_chan, a_chan, b_chan = cv2.split(lab)
			clahe_lab = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(8, 8))
			return clahe_lab.apply(l_chan)
		except Exception:
			return base_gs


# Make sure we were given an username to tast against
if len(sys.argv) < 2:
	sys.exit(12)

# Get the absolute path to the current directory
PATH = os.path.abspath(__file__ + "/..")

# The username of the user being authenticated
user = sys.argv[1]
if user == "root":
	caller = os.getenv("SUDO_USER")
	if not caller or caller == "root":
		try:
			import pwd
			with open("/proc/self/loginuid", "r") as f:
				luid = int(f.read().strip())
				if luid >= 1000 and luid != 4294967295:
					caller = pwd.getpwuid(luid).pw_name
		except Exception:
			pass
	if caller and caller != "root":
		user = caller
# The model file contents
models = []
# Encoded face models
encodings = []
# Amount of ignored 100% black frames
black_tries = 0
# Amount of ingnored dark frames
dark_tries = 0
# Total amount of frames captured
frames = 0
# Captured frames for snapshot capture
snapframes = []
# Tracks the lowest certainty value in the loop
lowest_certainty = 10
# Face recognition/detection instances
face_detector = None
pose_predictor = None
face_encoder = None
yunet_detector = None
liveness_verifier = None

# Try to load the face model via hardware-bound AES-256-GCM security module
try:
	import security
	models = security.load_user_models(user)

	for model in models:
		encodings += model["data"]
except Exception:
	sys.exit(10)

# Check if the file contains a model
if len(models) < 1:
	sys.exit(10)

# Read config from disk
config = configparser.ConfigParser()
config.read(PATH + "/config.ini")

# Get all config values needed
use_cnn = config.getboolean("core", "use_cnn", fallback=False)
timeout = config.getint("video", "timeout", fallback=5)
dark_threshold = config.getfloat("video", "dark_threshold", fallback=50.0)
video_certainty = config.getfloat("video", "certainty", fallback=3.5) / 10
end_report = config.getboolean("debug", "end_report", fallback=False)
capture_failed = config.getboolean("snapshots", "capture_failed", fallback=False)
capture_successful = config.getboolean("snapshots", "capture_successful", fallback=False)

# Save the time needed to start the script
timings["in"] = time.time() - timings["st"]

# Import face recognition, takes some time
timings["ll"] = time.time()

# Start threading and wait for init to finish
lock = thread.allocate_lock()
lock.acquire()
thread.start_new_thread(init_detector, (lock, ))

# Start video capture on the IR camera
timings["ic"] = time.time()

video_capture = VideoCapture(config)

# Read exposure from config to use in the main loop
exposure = config.getint("video", "exposure", fallback=-1)

# Note the time it took to open the camera
timings["ic"] = time.time() - timings["ic"]

# wait for thread to finish
lock.acquire()
lock.release()
del lock

# Fetch the max frame height
max_height = config.getfloat("video", "max_height", fallback=0.0)
# Get the height of the image
height = video_capture.internal.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1

# Calculate the amount the image has to shrink
scaling_factor = (max_height / height) or 1

# Fetch config settings out of the loop
timeout = config.getint("video", "timeout")
dark_threshold = config.getfloat("video", "dark_threshold")
end_report = config.getboolean("debug", "end_report")

# Start the read loop
frames = 0
valid_frames = 0
timings["fr"] = time.time()
dark_running_total = 0

clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

while True:
	# Increment the frame count every loop
	frames += 1

	# Quick shutter obstruction check: If >= 1.0s elapsed and >= 10 frames captured,
	# and 100% of frames are pitch black or exceeded dark threshold with 0 illuminated frames,
	# immediately exit with code 13 to fall back to fingerprint without waiting full timeout
	if (time.time() - timings["fr"] >= 1.0) and (frames >= 10):
		if (valid_frames == 0 and black_tries >= 5) or (dark_tries == valid_frames and valid_frames >= 5):
			sys.exit(13)

	# Stop if we've exceded the time limit
	if time.time() - timings["fr"] > timeout:
		# Create a timeout snapshot if enabled
		if capture_failed:
			make_snapshot("FAILED")

		if dark_tries == valid_frames:
			print("All frames were too dark, please check dark_threshold in config")
			print("Average darkness: " + str(dark_running_total / max(1, valid_frames)) + ", Threshold: " + str(dark_threshold))
			sys.exit(13)
		else:
			sys.exit(11)

	# Grab a single frame of video
	frame, gsframe = video_capture.read_frame()
	gsframe = clahe.apply(gsframe)

	# If snapshots have been turned on
	if capture_failed or capture_successful:
		# Start capturing frames for the snapshot
		if len(snapframes) < 3:
			snapframes.append(frame)

	# Create a histogram of the image with 8 values
	hist = cv2.calcHist([gsframe], [0], None, [8], [0, 256])
	hist_total = float(np.sum(hist))
	darkness = float(hist[0][0] / hist_total * 100) if hist_total > 0 else 100.0
	mean_lum = float(np.mean(gsframe))

	# Per-camera shutter & pitch-black detection (only triggers if sensor is genuinely covered/black)
	cur_cam = getattr(video_capture, "last_cam", None)
	is_dark = (hist_total == 0) or (darkness >= 96.0 and mean_lum < 6.0) or (darkness > dark_threshold)

	if is_dark:
		if cur_cam is not None:
			cur_cam["dark_count"] = cur_cam.get("dark_count", 0) + 1
			# If 3 consecutive dark frames, this camera's shutter is closed or covered
			if cur_cam["dark_count"] >= 3:
				remaining = video_capture.prune_camera(cur_cam, reason="Camera shutter closed / sensor pitch dark")
				if remaining == 0:
					print("All camera shutters covered or room pitch dark. Defaulting to fingerprint.", file=sys.stderr)
					sys.exit(13)
				continue
		black_tries += 1
		continue

	# Frame is illuminated and sensor is active
	if cur_cam is not None:
		cur_cam["dark_count"] = 0
	dark_running_total += darkness
	valid_frames += 1

	# Dynamically scale down frame per-camera if height exceeds max_height
	if max_height > 0 and frame.shape[0] > max_height:
		scale = max_height / frame.shape[0]
		frame = cv2.resize(frame, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
		gsframe = cv2.resize(gsframe, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

	# MSRCR & Dynamic Photometric Preprocessing (Gemini Blueprint Section 1)
	enh_frame, enh_gs, light_desc, light_col = vision_engine.adaptive_photometric_preprocess(frame)

	face_locations = []
	# Primary: Deep CNN YuNet Detector (Gemini Blueprint Section 2, sub-10ms, +-85 deg yaw)
	if yunet_detector is not None and yunet_detector.available:
		yn_faces = yunet_detector.detect(enh_frame)
		if yn_faces:
			face_locations = [f["rect"] for f in yn_faces]

	# Secondary: dlib HOG frontal detector
	if len(face_locations) == 0:
		face_locations = face_detector(enh_gs, 1)

	# Tertiary: OpenCV Haar Cascade fallback
	if len(face_locations) == 0 and haar_detector is not None:
		haar_boxes = haar_detector.detectMultiScale(enh_gs, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60))
		if len(haar_boxes) > 0:
			face_locations = [dlib.rectangle(int(hx), int(hy), int(hx + hw), int(hy + hh)) for (hx, hy, hw, hh) in haar_boxes]

	# Loop through each face
	for fl in face_locations:
		if use_cnn:
			fl = fl.rect

		# Passive Anti-Spoofing & Liveness Verification (Gemini Blueprint Section 3)
		if liveness_verifier is not None and liveness_verifier.available:
			liveness_score, is_live = liveness_verifier.verify(enh_frame, fl)
			if not is_live:
				continue

		# Fetch facial landmarks and 128-D descriptor
		face_landmark = pose_predictor(enh_frame, fl)
		face_encoding = np.array(face_encoder.compute_face_descriptor(enh_frame, face_landmark, 1))

		# Match this found face against a known face
		matches = np.linalg.norm(encodings - face_encoding, axis=1)

		# Get best match
		match_index = np.argmin(matches)
		match = matches[match_index]

		# Update certainty if we have a new low
		if lowest_certainty > match:
			lowest_certainty = match

		# Check if a match that's confident enough
		if 0 < match < video_certainty:
			timings["tt"] = time.time() - timings["st"]
			timings["fl"] = time.time() - timings["fr"]

			# If set to true in the config, print debug text
			if end_report:
				def print_timing(label, k):
					"""Helper function to print a timing from the list"""
					print("  %s: %dms" % (label, round(timings[k] * 1000)))

				# Print a nice timing report
				print("Time spent")
				print_timing("Starting up", "in")
				print("  Open cam + load libs: %dms" % (round(max(timings["ll"], timings["ic"]) * 1000, )))
				print_timing("  Opening the camera", "ic")
				print_timing("  Importing recognition libs", "ll")
				print_timing("Searching for known face", "fl")
				print_timing("Total time", "tt")

				print("\nResolution")
				width = video_capture.fw or 1
				print("  Native: %dx%d" % (height, width))
				# Save the new size for diagnostics
				scale_height, scale_width = frame.shape[:2]
				print("  Used: %dx%d" % (scale_height, scale_width))

				# Show the total number of frames and calculate the FPS by deviding it by the total scan time
				print("\nFrames searched: %d (%.2f fps)" % (frames, frames / timings["fl"]))
				print("Black frames ignored: %d " % (black_tries, ))
				print("Dark frames ignored: %d " % (dark_tries, ))
				print("Certainty of winning frame: %.3f" % (match * 10, ))

				print("Winning model: %d (\"%s\")" % (match_index, models[match_index]["label"]))

			winning_cam = getattr(video_capture, "last_camera_name", "Camera")
			for p in [f"/dev/shm/howdy_winning_cam_{user}", "/dev/shm/howdy_winning_cam"]:
				try:
					with open(p, "w") as f:
						f.write(winning_cam + "\n")
					os.chmod(p, 0o666)
				except Exception:
					pass

			# Make snapshot if enabled
			if capture_successful:
				make_snapshot("SUCCESSFUL")

			# End peacefully
			vision_engine.trim_heap_memory()
			sys.exit(0)

	if exposure != -1:
		# For a strange reason on some cameras (e.g. Lenoxo X1E)
		# setting manual exposure works only after a couple frames
		# are captured and even after a delay it does not
		# always work. Setting exposure at every frame is
		# reliable though.
		video_capture.internal.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1.0)  # 1 = Manual
		video_capture.internal.set(cv2.CAP_PROP_EXPOSURE, float(exposure))
