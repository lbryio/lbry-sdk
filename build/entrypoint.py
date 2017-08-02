# https://github.com/pyinstaller/pyinstaller/wiki/Recipe-Setuptools-Entry-Point
def Entrypoint(dist, group, name,
               scripts=None, pathex=None, binaries=None, datas=None,
               hiddenimports=None, hookspath=None, excludes=None, runtime_hooks=None,
               cipher=None, win_no_prefer_redirects=False, win_private_assemblies=False):
    import pkg_resources

    # get toplevel packages of distribution from metadata
    def get_toplevel(dist):
        distribution = pkg_resources.get_distribution(dist)
        if distribution.has_metadata('top_level.txt'):
            return list(distribution.get_metadata('top_level.txt').split())
        else:
            return []

    hiddenimports = hiddenimports or []
    packages = []
    for distribution in hiddenimports:
        packages += get_toplevel(distribution)

    scripts = scripts or []
    pathex = pathex or []
    # get the entry point
    ep = pkg_resources.get_entry_info(dist, group, name)
    # insert path of the egg at the verify front of the search path
    pathex = [ep.dist.location] + pathex
    # script name must not be a valid module name to avoid name clashes on import
    script_path = os.path.join(workpath, name + '-script.py')
    print "creating script for entry point", dist, group, name
    with open(script_path, 'w') as fh:
        fh.write("import {0}\n".format(ep.module_name))
        fh.write("{0}.{1}()\n".format(ep.module_name, '.'.join(ep.attrs)))
        for package in packages:
            fh.write("import {0}\n".format(package))

    return Analysis([script_path] + scripts,
                    pathex=pathex,
                    binaries=binaries,
                    datas=datas,
                    hiddenimports=hiddenimports,
                    hookspath=hookspath,
                    excludes=excludes,
                    runtime_hooks=runtime_hooks,
                    cipher=cipher,
                    win_no_prefer_redirects=win_no_prefer_redirects,
                    win_private_assemblies=win_private_assemblies
                    )
