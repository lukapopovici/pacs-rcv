from pybind11.setup_helpers import Pybind11Extension
from setuptools import setup

setup(
    ext_modules=[
        Pybind11Extension("fast_processor", ["fast_processor.cpp"])
    ]
)