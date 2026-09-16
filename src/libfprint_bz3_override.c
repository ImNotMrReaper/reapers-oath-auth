#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>

typedef void (*set_thresh_fn)(void *dev, int thresh);
typedef const char * (*get_driver_fn)(void *dev);
typedef const char * (*get_name_fn)(void *dev);
typedef void (*real_identify_fn)(void *dev, void *prints, void *cancellable, void *match_cb, void *match_data, void *match_destroy, void *cb, void *user_data);
typedef void (*real_verify_fn)(void *dev, void *print, void *cancellable, void *match_cb, void *match_data, void *match_destroy, void *cb, void *user_data);
typedef void (*real_open_fn)(void *dev, void *cancellable, void *cb, void *user_data);

static set_thresh_fn real_set_thresh = NULL;
static get_driver_fn real_get_driver = NULL;
static get_name_fn real_get_name = NULL;
static real_identify_fn real_identify = NULL;
static real_verify_fn real_verify = NULL;
static real_open_fn real_open = NULL;

static void init_symbols() {
    if (!real_set_thresh) {
        real_set_thresh = (set_thresh_fn)dlsym(RTLD_DEFAULT, "fpi_image_device_set_bz3_threshold");
        if (!real_set_thresh) {
            // try loading libfprint-2-tod.so.1
            void *h = dlopen("/usr/lib/x86_64-linux-gnu/libfprint-2-tod.so.1", RTLD_NOW | RTLD_GLOBAL);
            if (h) {
                real_set_thresh = (set_thresh_fn)dlsym(h, "fpi_image_device_set_bz3_threshold");
            }
        }
    }
    if (!real_get_driver) real_get_driver = (get_driver_fn)dlsym(RTLD_DEFAULT, "fp_device_get_driver");
    if (!real_get_name) real_get_name = (get_name_fn)dlsym(RTLD_DEFAULT, "fp_device_get_name");
    if (!real_identify) real_identify = (real_identify_fn)dlsym(RTLD_NEXT, "fp_device_identify");
    if (!real_verify) real_verify = (real_verify_fn)dlsym(RTLD_NEXT, "fp_device_verify");
    if (!real_open) real_open = (real_open_fn)dlsym(RTLD_NEXT, "fp_device_open");
}

static void apply_bz3_tuning(void *dev, int target_thresh) {
    init_symbols();
    if (!dev || !real_set_thresh) return;

    const char *driver = real_get_driver ? real_get_driver(dev) : NULL;
    const char *name = real_get_name ? real_get_name(dev) : "Unknown";

    // Only apply to optical image devices (uru4000 or optical)
    if (driver && (strcmp(driver, "uru4000") == 0 || strstr(driver, "uru") || (name && strstr(name, "Digital Persona")))) {
        if (target_thresh <= 0 || target_thresh > 100) target_thresh = 20;

        real_set_thresh(dev, target_thresh);
        syslog(LOG_AUTH | LOG_INFO, "[REAPER-BIOMETRIC] Adjusted %s (%s) Bozorth3 match threshold to %d", name, driver, target_thresh);
    }
}

void fp_device_identify(void *dev, void *prints, void *cancellable, void *match_cb, void *match_data, void *match_destroy, void *cb, void *user_data) {
    // For identification & enrollment duplicate checking, use standard strict threshold (default 40)
    // to avoid false-positive duplicate rejections during multi-finger enrollment.
    const char *env_ident = getenv("FP_BZ3_IDENTIFY_THRESHOLD");
    const char *env_thresh = getenv("FP_BZ3_THRESHOLD");
    int ident_thresh = env_ident ? atoi(env_ident) : (env_thresh ? atoi(env_thresh) : 14);
    apply_bz3_tuning(dev, ident_thresh);
    init_symbols();
    if (real_identify) {
        real_identify(dev, prints, cancellable, match_cb, match_data, match_destroy, cb, user_data);
    }
}

void fp_device_verify(void *dev, void *print, void *cancellable, void *match_cb, void *match_data, void *match_destroy, void *cb, void *user_data) {
    // For verification during authentication, use tuned sensitive threshold (default 14)
    const char *env_thresh = getenv("FP_BZ3_THRESHOLD");
    int threshold = env_thresh ? atoi(env_thresh) : 14;
    apply_bz3_tuning(dev, threshold);
    init_symbols();
    if (real_verify) {
        real_verify(dev, print, cancellable, match_cb, match_data, match_destroy, cb, user_data);
    }
}

void fp_device_open(void *dev, void *cancellable, void *cb, void *user_data) {
    init_symbols();
    if (real_open) {
        real_open(dev, cancellable, cb, user_data);
    }
}

