"""Legacy package metadata; runtime installation uses the pinned manifests."""

import sys

from setuptools import find_packages, setup


_BLOCKED_INSTALL_COMMANDS = {"bdist_wheel", "develop", "install"}
if _BLOCKED_INSTALL_COMMANDS.intersection(sys.argv[1:]):
    raise SystemExit(
        "Runtime installation through setup.py is intentionally blocked. "
        "Install the selected torch profile first, then run "
        "'python -m pip install -r requirements.txt'."
    )

setup(
    name="speech_to_information",
    version="0.1.0",
    description="Legacy metadata for the SpeechToInformation application",
    packages=find_packages(),
    python_requires="==3.11.*",
    install_requires=[],
)
