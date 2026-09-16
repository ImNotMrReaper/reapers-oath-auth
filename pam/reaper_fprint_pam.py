# PAM interface in Python for Digital Persona & Multi-Device Fingerprint Engine
import subprocess
import os
import syslog

def doAuth(pamh):
    try:
        user = pamh.get_user()
    except Exception:
        user = None

    if not user:
        return pamh.PAM_USER_UNKNOWN

    syslog.openlog("[DP4500-AUTH]", 0, syslog.LOG_AUTH)
    syslog.syslog(syslog.LOG_INFO, "Initiating multi-device fingerprint authentication for " + str(user))

    try:
        # Check /usr/local/bin/dp-auth first, then fallback to /usr/local/bin/reaper-fprint-auth
        bin_path = "/usr/local/bin/dp-auth"
        if not os.path.isfile(bin_path):
            bin_path = "/usr/local/bin/reaper-fprint-auth"

        proc = None
        try:
            proc = subprocess.Popen(
                [bin_path, user],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            for line in iter(proc.stdout.readline, ''):
                clean_line = line.strip()
                if clean_line:
                    try:
                        pamh.conversation(pamh.Message(pamh.PAM_TEXT_INFO, clean_line))
                    except Exception:
                        pass

            proc.wait()
            status = proc.returncode

            if status == 0:
                try:
                    pamh.conversation(pamh.Message(pamh.PAM_TEXT_INFO, "Fingerprint approved."))
                except Exception:
                    pass
                syslog.syslog(syslog.LOG_INFO, "Fingerprint approved for " + str(user))
                syslog.closelog()
                return pamh.PAM_SUCCESS
            elif status == 2:
                syslog.syslog(syslog.LOG_INFO, "No enrolled fingerprints for " + str(user))
                syslog.closelog()
                return pamh.PAM_AUTHINFO_UNAVAIL
            else:
                syslog.syslog(syslog.LOG_INFO, "Fingerprint authentication failed or timed out for " + str(user))
                syslog.closelog()
                return pamh.PAM_AUTH_ERR
        finally:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

    except Exception as e:
        syslog.syslog(syslog.LOG_ERR, "Execution error: " + str(e))
        syslog.closelog()
        return pamh.PAM_AUTHINFO_UNAVAIL

def pam_sm_authenticate(pamh, flags, args):
    return doAuth(pamh)

def pam_sm_open_session(pamh, flags, args):
    return pamh.PAM_SUCCESS

def pam_sm_close_session(pamh, flags, argv):
    return pamh.PAM_SUCCESS

def pam_sm_setcred(pamh, flags, argv):
    return pamh.PAM_SUCCESS

def pam_sm_chauthtok(pamh, flags, argv):
    return pamh.PAM_SUCCESS
