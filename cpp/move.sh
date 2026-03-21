python3 -m venv venv
source venv/bin/activate
pip install setuptools pybind11 
python setup.py build_ext --inplace
