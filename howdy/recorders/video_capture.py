import os
os.environ["OPENCV_LOG_LEVEL"] = "OFF"
os.environ["GST_DEBUG"] = "0"

import fcntl
import struct
import glob
import re
import sys
import time
import configparser
import concurrent.futures
import subprocess
import cv2

VIDIOC_QUERYCAP = 0x80685600


def format_camera_name(card: str, bus: str = "", dev_path: str = "") -> str:
    """Format clean, descriptive camera name from V4L2 card/bus or device path"""
    clean = card.replace("_", " ").strip()
    clean = re.sub(r':\s*[A-Za-z0-9_\s]*$', '', clean).strip()
    if "Brio" in clean:
        if not clean.startswith("Logitech"):
            clean = f"Logitech {clean}"
    elif "Integrated" in clean and "Webcam" in clean:
        clean = "Integrated Webcam FHD"
    if not clean:
        clean = os.path.basename(dev_path)
    return clean


def discover_capture_devices():
    """Discover all active V4L2 video capture devices via kernel ioctl (0.1ms query).
    Validates genuine video capture capabilities and filters out metadata/telemetry nodes.
    Works with USB webcams, laptop integrated cameras, IR sensors, capture cards, and virtual cameras.
    """
    cams = []
    for dev in sorted(glob.glob("/dev/video*")):
        try:
            fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
            buf = bytearray(104)
            fcntl.ioctl(fd, VIDIOC_QUERYCAP, buf)
            os.close(fd)
            card = buf[16:48].split(b'\x00', 1)[0].decode('utf-8', 'replace')
            bus = buf[48:80].split(b'\x00', 1)[0].decode('utf-8', 'replace')
            version, capabilities, device_caps = struct.unpack('<III', buf[80:92])
            caps = device_caps if (capabilities & 0x80000000) else capabilities
            # V4L2_CAP_VIDEO_CAPTURE (0x00000001) or V4L2_CAP_VIDEO_CAPTURE_MPLANE (0x00001000)
            is_capture = bool(caps & (0x00000001 | 0x00001000))
            if is_capture:
                real_path = os.path.realpath(dev)
                if not any(c['path'] == real_path for c in cams):
                    cams.append({
                        'path': real_path,
                        'name': format_camera_name(card, bus, dev),
                        'card': card,
                        'bus': bus
                    })
        except Exception:
            pass

    # Prioritize external USB webcams over integrated laptop cameras so the primary monitor camera captures first
    cams.sort(key=lambda c: 0 if ("integrated" not in c["name"].lower() and "webcam" not in c["name"].lower() and "laptop" not in c["name"].lower()) else 1)
    return cams


def calibrate_camera_hardware(dev_path: str, name: str):
    """Calibrate camera sensor hardware controls dynamically based on device capabilities"""
    try:
        clean = name.lower()
        if "brio" in clean or "logitech" in clean:
            # Logitech Brio 100: range 0..255 (default 128 -> set to crisp 160)
            # Disable dynamic framerate throttle to lock to solid 30 FPS (latency 67ms -> 33ms)
            subprocess.run(
                ["v4l2-ctl", "-d", dev_path, "--set-ctrl=sharpness=160", "--set-ctrl=exposure_dynamic_framerate=0"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
            )
        elif "integrated" in clean or "webcam" in clean:
            # Dell Integrated FHD sensor: range 1..7 (set to maximum 7)
            subprocess.run(
                ["v4l2-ctl", "-d", dev_path, "--set-ctrl=sharpness=7"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
            )
        else:
            # General cameras
            subprocess.run(
                ["v4l2-ctl", "-d", dev_path, "--set-ctrl=sharpness=7"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
            )
    except Exception:
        pass


def open_single_camera(dev_info: dict, force_mjpeg: bool = False, fw: int = -1, fh: int = -1):
    """Open and verify a single V4L2 camera device with dynamic hardware sensor calibration"""
    dev_path = dev_info["path"]
    name = dev_info["name"]
    try:
        # Dynamic hardware calibration (sharpness, 30 FPS lock)
        calibrate_camera_hardware(dev_path, name)

        cap = cv2.VideoCapture(dev_path, cv2.CAP_V4L2)
        if force_mjpeg:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        if fw != -1:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, fw)
        if fh != -1:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, fh)
        cap.set(cv2.CAP_PROP_FPS, 30)

        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        if cap.isOpened() and cap.grab():
            return {"path": dev_path, "name": name, "cap": cap}
        else:
            cap.release()
    except Exception:
        pass
    return None


class VideoCapture:
    """Universal plug-and-play multi-camera capture recorder with parallel arming and hot-unplug pruning"""
    def __init__(self, config):
        if isinstance(config, str):
            self.config = configparser.ConfigParser()
            self.config.read(config)
        else:
            self.config = config

        self.fw = self.config.getint("video", "frame_width", fallback=-1)
        self.fh = self.config.getint("video", "frame_height", fallback=-1)
        self.force_mjpeg = self.config.getboolean("video", "force_mjpeg", fallback=False)
        self.active_cameras = []
        self.cam_index = 0
        self.last_camera_name = "Camera"
        self.last_camera_path = ""
        self.device_path = None

        # 1. Discover all genuine V4L2 capture devices
        candidates = discover_capture_devices()

        # Hardware Lid Gate: Check ACPI clamshell state
        try:
            import vision_engine
            if vision_engine.is_lid_closed():
                external_cams = [c for c in candidates if "integrated" not in c["name"].lower() and "webcam" not in c["name"].lower()]
                if external_cams:
                    candidates = external_cams
                else:
                    print("[Howdy] Clamshell lid closed and no external camera armed; bypassing camera to fingerprint.", file=sys.stderr)
                    sys.exit(13)
        except Exception:
            pass

        # Check default_path fallback if candidates empty
        default_path = self.config.get("video", "device_path", fallback="/dev/video0")
        if os.path.exists(default_path) and not any(c["path"] == os.path.realpath(default_path) for c in candidates):
            candidates.insert(0, {
                "path": os.path.realpath(default_path),
                "name": "Default Camera",
                "card": "",
                "bus": ""
            })

        if not candidates:
            # Clean exit 13 for PAM fallback to fingerprint
            print("[Howdy] No V4L2 video capture devices discovered.", file=sys.stderr)
            sys.exit(13)

        # 2. Open ALL candidate cameras simultaneously in parallel (Zero delay)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(candidates))) as executor:
            opened = list(executor.map(
                lambda c: open_single_camera(c, self.force_mjpeg, self.fw, self.fh),
                candidates
            ))

        self.active_cameras = [cam for cam in opened if cam is not None]

        if not self.active_cameras:
            print("[Howdy] Failed to initialize any active camera streams. Defaulting to fingerprint/password.", file=sys.stderr)
            sys.exit(13)

        self.internal = self.active_cameras[0]["cap"]
        self.device_path = self.active_cameras[0]["path"]
        self.last_camera_name = self.active_cameras[0]["name"]
        self.last_camera_path = self.active_cameras[0]["path"]

    def read_frame(self):
        """Interleave captures across all armed cameras in high-speed round-robin with hot-unplug tolerance"""
        while self.active_cameras:
            if self.cam_index >= len(self.active_cameras):
                self.cam_index = 0

            cam = self.active_cameras[self.cam_index]

            try:
                ret, frame = cam["cap"].read()
            except Exception:
                ret, frame = False, None

            if ret and frame is not None:
                self.last_camera_name = cam["name"]
                self.last_camera_path = cam["path"]
                self.internal = cam["cap"]
                self.last_cam = cam
                self.cam_index = (self.cam_index + 1) % len(self.active_cameras)

                try:
                    gsframe = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                except RuntimeError:
                    gsframe = frame
                except cv2.error:
                    print("\nAn error occurred in OpenCV\n", file=sys.stderr)
                    raise

                return frame, gsframe

            # Read failed -> camera was disconnected, stalled, or unplugged
            print(f"[Howdy] Camera disconnected/dropped: {cam['name']} ({cam['path']})", file=sys.stderr)
            try:
                cam["cap"].release()
            except Exception:
                pass

            self.active_cameras.pop(self.cam_index)
            if self.active_cameras:
                self.cam_index = self.cam_index % len(self.active_cameras)
                self.internal = self.active_cameras[self.cam_index]["cap"]
                self.device_path = self.active_cameras[self.cam_index]["path"]
            else:
                break

        print("[Howdy] All camera feeds lost. Defaulting to fingerprint/password.", file=sys.stderr)
        sys.exit(13)

    def get_current_camera(self):
        """Get metadata dict for the camera that captured the most recent frame"""
        return getattr(self, "last_cam", None)

    def prune_camera(self, cam, reason="Camera shutter covered / sensor dark"):
        """Safely release and disconnect a camera, defaulting to remaining cameras"""
        if not cam or cam not in self.active_cameras:
            return len(self.active_cameras)

        print(f"[Howdy] {reason}: {cam['name']} ({cam['path']}). Sensor turned off.", file=sys.stderr)
        try:
            cam["cap"].release()
        except Exception:
            pass

        self.active_cameras.remove(cam)
        if self.active_cameras:
            self.cam_index = self.cam_index % len(self.active_cameras)
            self.internal = self.active_cameras[self.cam_index]["cap"]
            self.device_path = self.active_cameras[self.cam_index]["path"]
            self.last_cam = self.active_cameras[self.cam_index]
        else:
            self.last_cam = None
        return len(self.active_cameras)

    def release(self):
        """Cleanly release all camera handles"""
        for cam in self.active_cameras:
            try:
                cam["cap"].release()
            except Exception:
                pass
        self.active_cameras.clear()

    def __del__(self):
        self.release()
