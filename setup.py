"""Installation script for the 'tacex' python package."""

import os
import toml

from pathlib import Path
from setuptools import setup, find_packages

# Minimum dependencies required prior to installation
INSTALL_REQUIRES = [
    "Kivy==2.3.1",
    "Kivy-Garden==0.1.5",
    "open3d>=0.18.0",
    "opencv-python>=4.11.0.86",
    "pydantic>=2.10.6",
    "pydantic_core>=2.27.2",
    "scikit-image>=0.24.0",
    "scipy>=1.13.0",
    "pygrabber",
]

with (Path(__file__).resolve().parent / "README.md").open() as readme_file:
    long_description = readme_file.read()

with (Path(__file__).resolve().parent / "VERSION").open() as f:
    version = f.read()

# Installation operation
setup(
    name="gelsight",
    package_dir={"": "src"},
    packages=["gelsight"],
    author="",
    maintainer="",
    url="https://github.com/DH-Ng/gsrobotics",
    version=version,
    description="Package for capturing output of gelsight sensors",
    long_description=long_description,
    long_description_content_type="text/markdown",
    keywords=["gelsight", "tactile", "robotics"],
    install_requires=INSTALL_REQUIRES,
    # dependency_links=PYTORCH_INDEX_URL,
    license="MIT",
    include_package_data=True,
    python_requires=">=3.10",
    classifiers=[
        "Natural Language :: English",
        "Programming Language :: Python :: 3.10",
    ],
    zip_safe=False,
)
