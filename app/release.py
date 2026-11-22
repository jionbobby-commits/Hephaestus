"""Single source of truth for the public Windows release download.

Update this module, VERSION and installer/Hephaestus.iss together when cutting a
new release. The web download entry reads /api/release at runtime, so no other
frontend file needs a version change.
"""

REPOSITORY = "jionbobby-commits/Hephaestus"
VERSION = "1.3.0"
TAG = f"v{VERSION}"
INSTALLER_NAME = f"Hephaestus-Setup-{VERSION}.exe"
# Rounded download size shown in the web entry. Updated after the final build.
INSTALLER_SIZE_BYTES = 22_442_819
DOWNLOAD_URL = (
    f"https://github.com/{REPOSITORY}/releases/download/{TAG}/{INSTALLER_NAME}"
)
RELEASE_PAGE_URL = f"https://github.com/{REPOSITORY}/releases/tag/{TAG}"


def release_info() -> dict:
    """Return the public metadata consumed by the web download entry."""
    return {
        "version": VERSION,
        "installer": INSTALLER_NAME,
        "size_bytes": INSTALLER_SIZE_BYTES,
        "download_url": DOWNLOAD_URL,
        "release_url": RELEASE_PAGE_URL,
        "platform": "Windows 10/11 x64",
    }
