# PAM interface in python, launches compare.py

# Import required modules
import subprocess
import os
import glob
import syslog

# pam-python is running python 2, so we use the old module here
try:
    import configparser as ConfigParser
except ImportError:
    import ConfigParser

# Read config from disk
config = ConfigParser.ConfigParser()
config.read(os.path.dirname(os.path.abspath(__file__)) + "/config.ini")


def doAuth(pamh):
	"""Starts authentication in a seperate process"""

	# Abort is Howdy is disabled
	if config.getboolean("core", "disabled"):
		return pamh.PAM_AUTHINFO_UNAVAIL

	# Abort if we're in a remote SSH env
	if config.getboolean("core", "ignore_ssh"):
		if "SSH_CONNECTION" in os.environ or "SSH_CLIENT" in os.environ or "SSHD_OPTS" in os.environ:
			return pamh.PAM_AUTHINFO_UNAVAIL

	# Abort if lid is closed (unless an external camera is connected)
	if config.getboolean("core", "ignore_closed_lid"):
		if any("closed" in open(f).read() for f in glob.glob("/proc/acpi/button/lid/*/state")):
			has_ext_cam = False
			try:
				by_id = "/dev/v4l/by-id"
				if os.path.isdir(by_id):
					for entry in os.listdir(by_id):
						if "Integrated" not in entry and "video" in entry:
							has_ext_cam = True
							break
			except Exception:
				pass
			if not has_ext_cam:
				return pamh.PAM_AUTHINFO_UNAVAIL

	# Set up syslog
	syslog.openlog("[HOWDY]", 0, syslog.LOG_AUTH)

	# Alert the user that we are doing face detection
	if config.getboolean("core", "detection_notice"):
		pamh.conversation(pamh.Message(pamh.PAM_TEXT_INFO, "Identifying face..."))

	# Determine target user (map 'root' to requesting user in sudo/polkit)
	target_user = pamh.get_user()
	auth_user = target_user
	if auth_user == "root":
		caller = None
		try:
			if hasattr(pamh, "ruser") and pamh.ruser:
				caller = str(pamh.ruser).strip()
		except Exception:
			pass
		if not caller or caller == "root":
			try:
				import pwd
				with open("/proc/self/loginuid", "r") as f:
					luid = int(f.read().strip())
					if luid >= 1000 and luid != 4294967295:
						caller = pwd.getpwuid(luid).pw_name
			except Exception:
				pass
		if not caller or caller == "root":
			caller = os.environ.get("SUDO_USER")
		if caller and caller != "root":
			auth_user = caller

	syslog.syslog(syslog.LOG_INFO, "Attempting facial authentication for user " + auth_user)

	# Run compare as python3 subprocess to circumvent python version and import issues
	status = subprocess.call(["/usr/bin/python3", "/lib/security/howdy/compare.py", auth_user])

	# Status 10 means we couldn't find any face models
	if status == 10:
		if not config.getboolean("core", "suppress_unknown"):
			pamh.conversation(pamh.Message(pamh.PAM_ERROR_MSG, "No face model known"))

		syslog.syslog(syslog.LOG_NOTICE, "Failure, no face model known")
		syslog.closelog()
		return pamh.PAM_USER_UNKNOWN

	# Status 11 means we exceded the maximum retry count
	elif status == 11:
		pamh.conversation(pamh.Message(pamh.PAM_ERROR_MSG, "Face detection timeout reached"))
		syslog.syslog(syslog.LOG_INFO, "Failure, timeout reached")
		syslog.closelog()
		return pamh.PAM_AUTH_ERR

	# Status 12 means we aborted
	elif status == 12:
		syslog.syslog(syslog.LOG_INFO, "Failure, general abort")
		syslog.closelog()
		return pamh.PAM_AUTH_ERR

	# Status 13 means all cameras are covered, dark, or disconnected
	elif status == 13:
		syslog.syslog(syslog.LOG_INFO, "Camera shutter covered or unavailable, defaulting to fingerprint")
		syslog.closelog()
		pamh.conversation(pamh.Message(pamh.PAM_TEXT_INFO, "Camera covered or unavailable, using fingerprint..."))
		return pamh.PAM_AUTH_ERR
	# Status 0 is a successful exit
	elif status == 0:
		# Show the success message if it isn't suppressed
		if not config.getboolean("core", "no_confirmation"):
			winning_cam = ""
			for p in [f"/dev/shm/howdy_winning_cam_{auth_user}", "/dev/shm/howdy_winning_cam"]:
				if os.path.isfile(p):
					try:
						with open(p, "r") as fp:
							winning_cam = fp.read().strip()
						os.remove(p)
						break
					except Exception:
						pass
			cam_str = (" [%s]" % winning_cam) if winning_cam else ""
			pamh.conversation(pamh.Message(pamh.PAM_TEXT_INFO, "Identified face as " + pamh.get_user() + cam_str))

		syslog.syslog(syslog.LOG_INFO, "Login approved")
		syslog.closelog()
		return pamh.PAM_SUCCESS

	# Otherwise, we can't discribe what happend but it wasn't successful
	pamh.conversation(pamh.Message(pamh.PAM_ERROR_MSG, "Unknown error: " + str(status)))
	syslog.syslog(syslog.LOG_INFO, "Failure, unknown error" + str(status))
	syslog.closelog()
	return pamh.PAM_SYSTEM_ERR


def pam_sm_authenticate(pamh, flags, args):
	"""Called by PAM when the user wants to authenticate, in sudo for example"""
	return doAuth(pamh)


def pam_sm_open_session(pamh, flags, args):
	"""Called when starting a session, such as su"""
	return doAuth(pamh)


def pam_sm_close_session(pamh, flags, argv):
	"""We don't need to clean anyting up at the end of a session, so returns true"""
	return pamh.PAM_SUCCESS


def pam_sm_setcred(pamh, flags, argv):
	"""We don't need set any credentials, so returns true"""
	return pamh.PAM_SUCCESS
