#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/operators.h>

#include "block_filter.h"

namespace py = pybind11;

PYBIND11_MODULE(lbrycrd, mod) {
    py::class_<PYBlockFilter, std::shared_ptr<PYBlockFilter>> clsPYBlockFilter(mod, "PYBlockFilter");
    
    clsPYBlockFilter.def(py::init<std::vector< std::vector< unsigned char > >&>());
    clsPYBlockFilter.def(py::init< std::vector< unsigned char > &>());
    clsPYBlockFilter.def(py::init< std::string &, std::vector< unsigned char > &>());
    clsPYBlockFilter.def("GetEncoded",(const std::vector< unsigned char >& (PYBlockFilter::*)()) &PYBlockFilter::GetEncoded);
    clsPYBlockFilter.def("Match", (bool (PYBlockFilter::*)(std::vector< unsigned char >&)) &PYBlockFilter::Match);
    clsPYBlockFilter.def("MatchAny", (bool (PYBlockFilter::*)(std::vector< std::vector< unsigned char > >&)) &PYBlockFilter::MatchAny);
}
