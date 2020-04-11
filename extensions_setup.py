# from https://github.com/pybind/python_example/blob/master/setup.py
import sys
import os
import setuptools
import glob
from setuptools import Extension
from setuptools.command.build_ext import build_ext


class get_pybind_include(object):
    """Helper class to determine the pybind11 include path

    The purpose of this class is to postpone importing pybind11
    until it is actually installed, so that the ``get_include()``
    method can be invoked. """

    def __init__(self, user=False):
        self.user = user

    def __str__(self):
        import pybind11
        return pybind11.get_include(self.user)

#claimtrie_sources = glob.glob('../lbrycrd/src/**/*.cpp')
#claimtrie_sources += glob.glob('../lbrycrd/src/**/*.c')
claimtrie_sources = []
ext_modules = [
    Extension(
        'lbrycrd',
        [
            os.path.join("..", "lbrycrd", "src", "claimtrie", "blob.cpp"),
            os.path.join("..", "lbrycrd", "src", "claimtrie", "uints.cpp"),
            os.path.join("..", "lbrycrd", "src", "claimtrie", "txoutpoint.cpp"),
            os.path.join("..", "lbrycrd", "src", "random.cpp"),
            os.path.join("..", "lbrycrd", "src", "support", "lockedpool.cpp"),
            os.path.join("..", "lbrycrd", "src", "support", "cleanse.cpp"),
            os.path.join("..", "lbrycrd", "src", "util", "time.cpp"),
            os.path.join("..", "lbrycrd", "src", "util", "threadnames.cpp"),
            os.path.join("..", "lbrycrd", "src", "hash.cpp"),
            os.path.join("..", "lbrycrd", "src", "fs.cpp"),
            os.path.join("..", "lbrycrd", "src", "logging.cpp"),
            os.path.join("..", "lbrycrd", "src", "uint256.cpp"),
            os.path.join("..", "lbrycrd", "src", "arith_uint256.cpp"),
            os.path.join("..", "lbrycrd", "src", "crypto", "sha512.cpp"),
            os.path.join("..", "lbrycrd", "src", "crypto", "hmac_sha512.cpp"),
            os.path.join("..", "lbrycrd", "src", "crypto", "ripemd160.cpp"),
            os.path.join("..", "lbrycrd", "src", "crypto", "chacha20.cpp"),
            os.path.join("..", "lbrycrd", "src", "primitives", "transaction.cpp"),
            os.path.join("..", "lbrycrd", "src", "primitives", "block.cpp"),
            os.path.join("..", "lbrycrd", "src", "blockfilter.cpp"),
            os.path.join("..", "lbrycrd", "src", "crypto", "sha256.cpp"),
            os.path.join("..", "lbrycrd", "src", "crypto", "siphash.cpp"),
            os.path.join("..", "lbrycrd", "src", "script", "script.cpp"),
            os.path.join("..", "lbrycrd", "src", "util", "strencodings.cpp"),
            os.path.join("..", "lbrycrd", "src", "util", "bytevectorhash.cpp"),
            os.path.join("lbrycrd_cpp_bindings", "block_filter.cpp"),
            os.path.join("lbrycrd_cpp_bindings", "lbrycrd.cpp"),
        ] + claimtrie_sources,
        include_dirs=[
            # Path to pybind11 headers
            get_pybind_include(),
            get_pybind_include(user=True),
            os.path.join("..", "lbrycrd", "src"),
            os.path.join("..", "lbrycrd", "src", "claimtrie"),
        ],
        libraries=['boost_thread', 'crypto', 'boost_chrono', 'boost_filesystem'],
        language='c++'
    ),
]


# As of Python 3.6, CCompiler has a `has_flag` method.
# cf http://bugs.python.org/issue26689
def has_flag(compiler, flagname):
    """Return a boolean indicating whether a flag name is supported on
    the specified compiler.
    """
    import tempfile
    with tempfile.NamedTemporaryFile('w', suffix='.cpp') as f:
        f.write('int main (int argc, char **argv) { return 0; }')
        try:
            compiler.compile([f.name], extra_postargs=[flagname])
        except setuptools.distutils.errors.CompileError:
            return False
    return True


def cpp_flag(compiler):
    """Return the -std=c++[11/14/17] compiler flag.

    The newer version is prefered over c++11 (when it is available).
    """
    flags = ['-std=c++17', '-std=c++14', '-std=c++11']

    for flag in flags:
        if has_flag(compiler, flag): return flag

    raise RuntimeError('Unsupported compiler -- at least C++11 support '
                       'is needed!')


class BuildExt(build_ext):
    """A custom build extension for adding compiler-specific options."""
    c_opts = {
        'msvc': ['/EHsc'],
        'unix': [],
    }
    l_opts = {
        'msvc': [],
        'unix': [],
    }

    if sys.platform == 'darwin':
        darwin_opts = ['-stdlib=libc++', '-mmacosx-version-min=10.14']
        c_opts['unix'] += darwin_opts
        l_opts['unix'] += darwin_opts

    def build_extensions(self):
        ct = self.compiler.compiler_type
        opts = self.c_opts.get(ct, [])
        opts.append('-DHAVE_WORKING_BOOST_SLEEP_FOR=1')
        link_opts = self.l_opts.get(ct, [])
        if ct == 'unix':
            opts.append('-DVERSION_INFO="%s"' % self.distribution.get_version())
            opts.append(cpp_flag(self.compiler))
            if has_flag(self.compiler, '-fvisibility=hidden'):
                opts.append('-fvisibility=hidden')
        elif ct == 'msvc':
            opts.append('/DVERSION_INFO=\\"%s\\"' % self.distribution.get_version())
        for ext in self.extensions:
            ext.extra_compile_args = opts
            ext.extra_link_args = link_opts
        build_ext.build_extensions(self)
