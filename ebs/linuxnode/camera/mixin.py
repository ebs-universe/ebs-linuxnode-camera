

import os
import yaml
from appdirs import user_data_dir, user_config_dir

from ebs.linuxnode.core.config import ElementSpec
from ebs.linuxnode.core.config import ItemSpec
from ebs.linuxnode.core.basenode import BaseIoTNode
from ebs.linuxnode.sysinfo.mixin import SysinfoMixin

from .info import CameraInfo
from .multicam import MultiCameraManager
from .utils import merge_dicts


class CameraMixin(SysinfoMixin, BaseIoTNode):
    def __init__(self, *args, **kwargs):
        super(CameraMixin, self).__init__(*args, **kwargs)
        self._camera_manager = None
        self._camera_aliases = None

    def install(self):
        super(CameraMixin, self).install()
        _elements = {
            'camera_preview_lowres': ElementSpec('camera_preview', "lowres", ItemSpec(bool, fallback=True)),
            'camera_aliases': ElementSpec('camera', 'aliases', ItemSpec(fallback='')),
            'camera_backend': ElementSpec('camera', 'backend', ItemSpec(fallback='opencv')),
            'camera_inherit_alias': ElementSpec('camera', 'inherit_alias', ItemSpec(bool, fallback=True)),
            'camera_publish_api': ElementSpec('camera', 'publish_api', ItemSpec(bool, fallback=False)),
        }
        for name, spec in _elements.items():
            self.config.register_element(name, spec)

    @property
    def camera_captures_path(self):
        if self.config.camera_publish_api:
            target = os.path.join(self.tempdir, 'captures')
        else:
            target = os.path.join(user_data_dir(self.appname), 'captures')
        os.makedirs(target, exist_ok=True)
        return target

    @property
    def camera_aliases(self):
        if self._camera_aliases is None:
            self._camera_aliases = \
                {k.strip(): v.strip() for k, v in (line.split("::", 1)
                 for line in self.config.camera_aliases.strip().splitlines() if line.strip())}
        return self._camera_aliases

    def sysinfo_install(self):
        super().sysinfo_install()
        self.sysinfo.install_module('cameras', CameraInfo)

    @property
    def cameras_config_file(self):
        rv = os.path.join(user_config_dir(self.appname), 'cameras.yml')
        return rv

    _cameras_config_default = {
                'default': {
                    'pipelines': {
                        'still': ['acquire', 'crop', 'denoise', 'save']
                    },
                    'acquire': {
                        'type': 'acquire',
                        'resolution': 'max',
                        'fps': 'min',
                        'buffer_size': 'min',
                        'delay': 3
                    },
                    "crop": {
                        'type': "crop",
                        'x1': 0,
                        'x2': 1,
                        'y1': 0,
                        'y2': 1
                    },
                    "denoise": {
                        "type": 'denoise',
                        "method": "nlm",
                        "params": {
                            "h": 10,
                            "hcolor": 10,
                            "template_window_size": 7,
                            "search_window_size": 21
                        }
                    },
                    "save": {
                        "type": 'save',
                        "format": "png",
                        "compression": 9
                    },
                }
            }

    @property
    def cameras_config(self):
        # TODO
        # This function should give a meaningful error if the config is
        # incomplete or invalid. Perhaps see tendril yaml handling?
        if os.path.exists(self.cameras_config_file):
            rv = yaml.safe_load(open(self.cameras_config_file, 'r'))
            rv = merge_dicts(self._cameras_config_default, rv)
        else:
            rv = self._cameras_config_default
        return rv

    @property
    def cameras(self):
        return self._camera_manager

    def start(self):
        super().start()
        self._camera_manager = MultiCameraManager(self, backend=self.config.camera_backend)

    def stop(self):
        self._camera_manager.exit_wait()
        super().stop()
