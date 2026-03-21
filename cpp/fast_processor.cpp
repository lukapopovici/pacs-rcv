#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <vector>
#include <string>

namespace py = pybind11;

std::string process_request(const std::string& payload, int priority) {
    return "processed_" + payload;
}

PYBIND11_MODULE(fast_processor, m) {
    m.def("process_request", &process_request, "Process a request at C++ speed");
}