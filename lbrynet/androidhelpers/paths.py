# App root files dir
# https://developer.android.com/reference/android/content/ContextWrapper.html#getFilesDir%28%29
def android_files_dir():
    return None


# Base internal storage path
def android_internal_storage_dir():
    return None


# Base external (SD card, if present) storage path
def android_external_storage_dir():
    return None


# Internal device storage (private app folder)
# https://developer.android.com/reference/android/content/ContextWrapper.html#getExternalFilesDirs(java.lang.String)
def android_app_internal_storage_dir():
    return None


# External (app folder on SD card, if present) storage
# https://developer.android.com/reference/android/content/ContextWrapper.html#getExternalFilesDirs(java.lang.String)
def android_app_external_storage_dir():
    return None