import inspect
from os.path import dirname, join

import sh
from pythonforandroid.util import ensure_dir
from pythonforandroid.toolchain import (
    Bootstrap, current_directory, info, info_main, shprint
)


class LBRYServiceBootstrap(Bootstrap):
    name = 'lbry-service'
    recipe_depends = ['genericndkbuild', 'python3']
    bootstrap_dir = dirname(__file__)

    def get_common_dir(self):
        return join(dirname(inspect.getfile(Bootstrap)), 'bootstraps', 'common')

    def run_distribute(self):
        info_main('# Creating Android project from build and {} bootstrap'.format(
            self.name))

        info('This currently just copies the build stuff straight from the build dir.')
        shprint(sh.rm, '-rf', self.dist_dir)
        shprint(sh.cp, '-r', self.build_dir, self.dist_dir)
        with current_directory(self.dist_dir):
            with open('local.properties', 'w') as fileh:
                fileh.write('sdk.dir={}'.format(self.ctx.sdk_dir))

        arch = self.ctx.archs[0]
        if len(self.ctx.archs) > 1:
            raise ValueError('built for more than one arch, but bootstrap cannot handle that yet')
        info('Bootstrap running with arch {}'.format(arch))

        with current_directory(self.dist_dir):
            info('Copying python distribution')

            self.distribute_libs(arch, [self.ctx.get_libs_dir(arch.arch)])
            self.distribute_aars(arch)
            self.distribute_javaclasses(self.ctx.javaclass_dir)

            python_bundle_dir = join('_python_bundle', '_python_bundle')
            ensure_dir(python_bundle_dir)
            site_packages_dir = self.ctx.python_recipe.create_python_bundle(
                join(self.dist_dir, python_bundle_dir), arch)

        self.strip_libraries(arch)
        self.fry_eggs(site_packages_dir)
        super().run_distribute()
