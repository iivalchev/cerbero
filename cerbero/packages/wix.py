# cerbero - a multi-platform build system for Open Source software
# Copyright (C) 2012 Andoni Morales Alastruey <ylatuya@gmail.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Library General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Library General Public License for more details.
#
# You should have received a copy of the GNU Library General Public
# License along with this library; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.

import os
import uuid
import shutil

from cerbero.utils import etree, to_winepath, shell
from cerbero.config import Platform, Architecture

WIX_SCHEMA = "http://schemas.microsoft.com/wix/2006/wi"


class WixBase():

    def __init__(self, config, package):
        self.config = config
        self.package = package
        self.platform = config.platform
        self.target_platform = config.target_platform
        self._with_wine = self.platform != Platform.WINDOWS
        self.prefix = config.prefix
        self.filled = False
        self.id_count = 0
        self.ids = {}

    def fill(self):
        if self.filled:
            return
        self._fill()
        self.filled = True

    def write(self, filepath):
        self.fill()
        tree = etree.ElementTree(self.root)
        tree.write(filepath, encoding='utf-8', pretty_print=True)

    def _format_level(self, selected):
        return selected and '1' or '2'

    def _format_absent(self, required):
        return required and 'disallow' or 'allow'

    def _add_root(self):
        self.root = etree.Element("Wix", xmlns=WIX_SCHEMA)

    def _format_id(self, string, replace_dots=False):
        ret = string
        ret = ret.replace('_', '__')
        for r in ['/', '-', ' ', '@', '+']:
            ret = ret.replace(r, '_')
        if replace_dots:
            ret = ret.replace('.', '')
        # For directories starting with a number
        return '_' + ret

    def _format_path_id(self, path, replace_dots=False):
        ret = self._format_id(os.path.split(path)[1], replace_dots)
        if ret not in self.ids:
            self.ids[ret] = 0
        else:
            self.ids[ret] += 1
        if self.ids[ret] != 0:
            ret = '%s_%s' % (ret, self.ids[ret])
        return ret

    def _get_uuid(self):
        return "%s" % uuid.uuid1()


class MergeModule(WixBase):
    '''
    Creates WiX merge modules from cerbero packages

    @ivar package: package with the info to build the merge package
    @type pacakge: L{cerbero.packages.package.Package}
    '''

    def __init__(self, config, files_list, package):
        WixBase.__init__(self, config, package)
        self.files_list = files_list
        self._dirnodes = {}

    def _fill(self):
        self._add_root()
        self._add_module()
        self._add_package()
        self._add_root_dir()
        self._add_files()

    def _add_module(self):
        self.module = etree.SubElement(self.root, "Module",
            Id=self._format_id(self.package.name),
            Version=self.package.version, Language='1033')

    def _add_package(self):
        self.pkg = etree.SubElement(self.module, "Package",
            Id=self.package.uuid or self._get_uuid(),
            Description=self.package.shortdesc,
            Comments=self.package.longdesc,
            Manufacturer=self.package.vendor)

    def _add_root_dir(self):
        self.rdir = etree.SubElement(self.module, "Directory",
            Id='TARGETDIR', Name='SourceDir')
        self._dirnodes[''] = self.rdir

    def _add_files(self):
        for f in self.files_list:
            self._add_file(f)

    def _add_directory(self, dirpath):
        if dirpath in self._dirnodes:
            return
        parentpath = os.path.split(dirpath)[0]
        if parentpath == []:
            parentpath = ['']

        if parentpath not in self._dirnodes:
            self._add_directory(parentpath)

        parent = self._dirnodes[parentpath]
        dirnode = etree.SubElement(parent, "Directory",
            Id=self._format_path_id(dirpath),
            Name=os.path.split(dirpath)[1])
        self._dirnodes[dirpath] = dirnode

    def _add_file(self, filepath):
        dirpath, filename = os.path.split(filepath)
        self._add_directory(dirpath)
        dirnode = self._dirnodes[dirpath]

        component = etree.SubElement(dirnode, 'Component',
            Id=self._format_path_id(filepath), Guid=self._get_uuid())

        filepath = os.path.join(self.prefix, filepath)
        p_id = self._format_path_id(filepath, True)
        if self._with_wine:
            filepath = to_winepath(filepath)
        etree.SubElement(component, 'File', Id=p_id, Name=filename,
                         Source=filepath)


class WixConfig(object):

    wix_config = 'wix/Config.wxi'

    def __init__(self, config, package):
        self.config_path = os.path.join(config.data_dir, self.wix_config)
        self.arch = config.target_arch
        self.package = package

    def write(self, output_dir):
        config_out_path = os.path.join(output_dir,
                os.path.basename(self.wix_config))
        shutil.copy(self.config_path, os.path.join(output_dir,
                    os.path.basename(self.wix_config)))
        replacements = {
            "@ProductID@": self.package.uuid,
            "@UpgradeCode@": self.package.uuid,
            "@Language@": '1033',
            "@Manufacturer@": self.package.vendor,
            "@Version@": self.package.version,
            "@PackageComments@": self.package.longdesc,
            "@Description@": self.package.shortdesc,
            "@ProjectURL": self.package.url,
            "@ProductName@": self.package.title,
            "@ProgramFilesFolder@": self._program_folder(),
            "@Platform@": self._platform()}
        shell.replace(config_out_path, replacements)
        return config_out_path

    def _program_folder(self):
        if self.arch == Architecture.X86:
            return 'ProgramFilesFolder'
        return 'ProgramFiles64Folder'

    def _platform(self):
        if self.arch == Architecture.X86_64:
            return 'x64'
        return 'x86'


class MSI(WixBase):
    '''Creates an installer package from a
       L{cerbero.packages.package.MetaPackage}

    @ivar package: meta package used to create the installer package
    @type package: L{cerbero.packages.package.MetaPackage}
    '''

    wix_sources = 'wix/installer.wxs'


    def __init__(self, config, package, packages_deps, wix_config, store):
        WixBase.__init__(self, config, package)
        self.packages_deps = packages_deps
        self.store = store
        self.wix_config = wix_config
        self._parse_sources()
        self._add_include()
        self.product = self.root.find(".//Product")

    def _parse_sources(self):
        sources_path = os.path.join(self.config.data_dir, self.wix_sources)
        with open(sources_path, 'r') as f:
            self.root = etree.fromstring(f.read())
        for element in self.root.iter():
            element.tag = element.tag[len(WIX_SCHEMA)+2:]
        self.root.set('xmlns', WIX_SCHEMA)
        self.product = self.root.find('Product')

    def _add_include(self):
        if self._with_wine:
            self.wix_config = to_winepath(self.wix_config)
        inc = etree.PI('include %s' % self.wix_config)
        self.root.insert(0, inc)

    def _fill(self):
        self._add_install_dir()
        self._add_merge_modules()

    def _add_merge_modules(self):
        self.main_feature = etree.SubElement(self.product, "Feature",
            Id=self._format_id(self.package.name),
            Title=self.package.title, Level='1', Display="expand",
            AllowAdvertise="no", ConfigurableDirectory="INSTALLDIR")

        packages = [(self.store.get_package(x[0]), x[1], x[2]) for x in
                    self.package.packages]

        # Remove empty packages
        packages = [x for x in packages if x[0] in self.packages_deps]

        # Fill the list of required packages
        req = [x[0] for x in packages if x[1] == True]
        required_packages = req[:]
        for p in req:
            required_packages.extend(self.store.get_package_deps(p))

        for package, required, selected in packages:
            if package in self.packages_deps:
                self._add_merge_module(package, required, selected,
                                       required_packages)

        # Add a merge module ref for all the packages
        for package in self.packages_deps:
            etree.SubElement(self.installdir, 'Merge',
                Id=self._package_id(package.name), Language='1033',
                SourceFile='%s.msm' % package.name, DiskId='1')

    def _add_dir(self, parent, dir_id, name):
        tdir = etree.SubElement(parent, "Directory",
            Id=dir_id, Name=name)
        return tdir

    def _add_install_dir(self):
        tdir = self._add_dir(self.product, 'TARGETDIR', 'SourceDir')
        pfdir = self._add_dir(tdir, 'ProgramFilesFolder', 'PFiles')
        install_dir = self.package.install_dir[self.target_platform]
        sdkdir = self._add_dir(pfdir, self._format_id(install_dir),
                               install_dir)
        self.installdir = self._add_dir(sdkdir, 'INSTALLDIR', '.')

    def _package_id(self, package_name):
        return self._format_id(package_name)

    def _add_merge_module(self, package, required, selected,
                          required_packages):
        # Create a new feature for this package
        feature = etree.SubElement(self.main_feature, 'Feature',
                Id=self._format_id(package.name), Title=package.shortdesc,
                Level=self._format_level(selected),
                Display='expand', Absent=self._format_absent(required))
        deps = self.store.get_package_deps(package)

        # Add all the merge modules required by this package, but excluding
        # all the ones that are forced to be installed
        if not required:
            mergerefs = list(set(deps) - set(required_packages))
        else:
            mergerefs = [x for x in deps if x in required_packages]

        for p in mergerefs:
            etree.SubElement(feature, "MergeRef",
                             Id=self._package_id(p.name))
        etree.SubElement(feature, "MergeRef",
                         Id=self._package_id(package.name))
