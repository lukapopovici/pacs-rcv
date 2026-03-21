import sys
import numpy
from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

# ── platform helpers ────────────────────────────────────────────────────────
is_windows = sys.platform == "win32"
is_mac     = sys.platform == "darwin"

ext = Pybind11Extension(
    "fast_processor",             # module name (import fast_processor)
    ["fast_processor.cpp"],       # source files — add more here

    # ── C++ standard ────────────────────────────────────────────────────────
    cxx_std=17,                   # 11 / 14 / 17 / 20

    # ── compiler optimisation flags ─────────────────────────────────────────
    extra_compile_args=[
        "/O2" if is_windows else "-O3",       # optimise fully
        "-march=native",                       # use all CPU features of this machine
        "-ffast-math",                         # relax IEEE float rules (big speedup)
        "-fopenmp",                            # enable OpenMP parallelism
        "-Wall", "-Wextra",                    # warnings (good for dev builds)
    ],

    # ── linker flags ────────────────────────────────────────────────────────
    extra_link_args=[
        "-fopenmp",               # must also link OpenMP
        "-lssl", "-lcrypto",      # OpenSSL (for real SHA-256 / AES)
        "-lz",                    # zlib (compression)
        "-lpthread",              # POSIX threads
    ],

    # ── header search paths ─────────────────────────────────────────────────
    include_dirs=[
        numpy.get_include(),      
        "./third_party/eigen",    
        "./third_party/rapidcsv", 
        "/usr/local/include",    
    ],

    # ── library search paths (where .so/.dylib/.lib files live) ─────────────
    library_dirs=[
        "/usr/local/lib",
        "./lib",
    ],

    # ── libraries to link against ───────────────────────────────────────────
    libraries=[
        "ssl", "crypto",          # OpenSSL
        "z",                      # zlib
        "pthread",                # threads
    ],

    # ── preprocessor defines ────────────────────────────────────────────────
    define_macros=[
        ("VERSION_INFO", "1.0.0"),          # accessible in C++ as VERSION_INFO
        ("NDEBUG", None),                   # disable asserts in release
        ("MY_FEATURE_ENABLED", "1"),        # feature flags
    ],

    # ── suppress all deprecation noise from pybind11 itself ─────────────────
    py_limited_api=False,
)

setup(
    name="fast_processor",
    version="1.0.0",
    author="You",
    description="CPU-bound hot paths in C++",
    ext_modules=[ext],
    cmdclass={"build_ext": build_ext},
    zip_safe=False,

    python_requires=">=3.8",
)