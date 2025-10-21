

"""
Discover all available V4L2 cameras.

Priority:
  1. /dev/v4l/by-id
    - Not implemented.
    - most stable if available, serial-based
    - this isn't available on any camera tested so far.
    - To be implemented and explicitly enabled in config when needed.
  2. /dev/v4l/by-path (stable, topology-based)
  3. /dev/video* direct nodes (fallback, unstable)
    - Not implemented.
    - Use case is really only with a single camera (?)
    - Consider using bus info from v4l2-ctl
"""

import re
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from collections import OrderedDict
from collections import namedtuple

from ebs.linuxnode.sysinfo.base import SysInfoBase

from .utils import merge_dicts
from .utils import decode_flags
from .utils import parse_fraction

CAMERA_SUPPORT = False

try:
    from linuxpy.video.device import Device
    from linuxpy.video.raw import Capability
    from linuxpy.video.raw import PixelFormat
    from linuxpy.video.raw import MetaFormat
    import cv2
    CAMERA_SUPPORT = True
except ImportError:
    print("Warning: camera support not available")
    CAMERA_SUPPORT = False


def _parse_formats(spec):
    formats = []
    for f in spec.formats:
        px_fmt = None
        if spec.device_capabilities & Capability.VIDEO_CAPTURE:
            try:
                px_fmt = PixelFormat(f.pixel_format).name
            except ValueError:
                pass
        if spec.device_capabilities & Capability.META_CAPTURE:
            try:
                px_fmt = MetaFormat(f.pixel_format).name
            except ValueError:
                pass
        if not px_fmt:
            px_fmt = f.pixel_format

        fmt = {
            "format": px_fmt,
            "description": f.description,
        }
        formats.append(fmt)
    return formats


def _parse_frame_info(spec, limits_only=True):
    f_sizes = spec.frame_sizes
    rv = sorted(
        list(set([frame_size(width=x.width, height=x.height) for x in f_sizes])),
        key=lambda x: x.width, reverse=True
    )

    rv = [{'width': x.width, 'height': x.height, 'frame_rates': []} for x in rv]

    for f_size in rv:
        for f_spec in f_sizes:
            if f_spec.width == f_size['width'] and f_spec.height == f_size['height']:
                f_size['frame_rates'].append(parse_fraction(f_spec.max_fps))
                f_size['frame_rates'].append(parse_fraction(f_spec.min_fps))
        f_size['frame_rates'] = sorted(list(set(f_size['frame_rates'])), key=lambda x: Fraction(x))

    if not limits_only:
        return rv
    else:
        # Use first element of result for highest resolution (img cap)
        # Use last element of result for lowest resolution (preview)
        return [rv[0], rv[-1]]


def _parse_channel_spec(spec):
    rv = {
        'card': spec.card,
        # 'driver': spec.driver,
        # 'bus': spec.bus_info,
        # 'version': spec.version,
        'device_capabilities': decode_flags(spec.device_capabilities, Capability),
        # 'capabilities': _decode_flags(spec.capabilities, Capability),
        'formats': _parse_formats(spec),
    }
    if spec.device_capabilities & Capability.VIDEO_CAPTURE:
        rv['frame_info'] = _parse_frame_info(spec)
    return rv


path_regex = re.compile(
    r"^(?:platform-[0-9a-f]+.pcie-)?"           # rpi has this prefix
    r"(?:pci-(?P<pci_id>[^-]+)-)?"              # optional pci
    r"(?:usb[v\d]*-(?P<usb_id>[^-]+)-)?"        # optional usb (handles "usb" or "usbv2")
    r"video-index(?P<chn_id>\d+)$"              # channel is required
)


def _repack_v4l_path_parts(parts, compact=True):
    rv = OrderedDict()
    if "pci" in parts.keys():
        domain, bus, slot, func = parts["pci"]
        if compact:
            rv["pci"] = f"{domain}:{bus}:{slot}.{func}"
        else:
            rv["pci"] = f"{domain:04x}:{bus:02x}:{slot:02x}.{func}"

    if "usb" in parts.keys():
        usb_parts = list(map(str, parts["usb"]))
        if len(usb_parts) > 1:
            usb_str = ":".join(usb_parts[:-1]) + "." + usb_parts[-1]
        else:
            usb_str = usb_parts[0]
        rv["usb"] = usb_str

    if "chn" in parts.keys():
        rv["chn"] = str(parts["chn"])

    # Build a compact display string
    compact_str = []
    if "pci" in rv:
        compact_str.append(f"pci-{rv['pci']}")
    if "usb" in rv:
        compact_str.append(f"usb-{rv['usb']}")
    if "chn" in rv:
        compact_str.append(f"ch{rv['chn']}")
    return "/".join(compact_str)


def _extract_v4l_path_parts(v4l_path):
    match = path_regex.match(v4l_path)
    if not match:
        return v4l_path

    pci_str = match.group("pci_id")
    usb_str = match.group("usb_id")
    chn_id = int(match.group("chn_id"))

    # Parse PCI: domain:bus:slot.func
    domain, bus, slot_func = pci_str.split(":")
    slot, func = slot_func.split(".")
    pci_tuple = (int(domain, 16), int(bus, 16), int(slot, 16), int(func))

    # Parse USB: split on : and .
    usb_parts = []
    for part in usb_str.replace(".", ":").split(":"):
        usb_parts.append(int(part))
    usb_tuple = tuple(usb_parts)

    parts = {
        "pci": pci_tuple,
        "usb": usb_tuple,
        "chn": chn_id,
        "str": ""
    }

    parts["str"] = _repack_v4l_path_parts(parts)
    return parts

frame_size = namedtuple('FrameSize', 'width, height')


class CameraInfo(SysInfoBase):
    def __init__(self, *args, inherit_alias=True, **kwargs):
        super(CameraInfo, self).__init__(*args, **kwargs)
        self._inherit_alias = inherit_alias
        self._detected = {}

    def install(self):
        super(CameraInfo, self).install()
        self._items = {
            'support': 'supported',
            'detected': 'detected'
        }

    def _get_alias(self, path_str):
        for alias, path in self.actual.camera_aliases.items():
            if path == path_str:
                return alias
        return None

    def _find_v4l_path_nodes(self):
        candidates = [
            Path("/dev/v4l/by-path"),
            Path("/dev/v4l2/by-path"),
        ]

        for base in candidates:
            if base.exists():
                nodes = []
                for dev in base.iterdir():
                    if "video-index" not in dev.name:
                        continue
                    try:
                        dev_path = dev.resolve()
                    except OSError:
                        continue
                    phy_path = _extract_v4l_path_parts(dev.name)
                    if not isinstance(phy_path, dict):
                        print(f"Unrecognized v4l node : {dev.name}")
                        continue
                    
                    alias = self._get_alias(phy_path["str"])
                    if not alias:
                        idx = str(dev_path).removeprefix("/dev/video")
                        alias = f"cam{idx}"
                    
                    nodes.append({
                        "phy_path": phy_path,
                        "dev_path": str(dev_path),
                        "alias": alias,
                    })
                    
                return nodes
        return None

    def _get_node_info(self, dev_path):
        """Extract metadata for one camera channel using linuxpy."""
        try:
            chn = Device(dev_path)
            chn.open()
        except Exception as e:
            return {
                "error": str(e),
            }
        info = _parse_channel_spec(chn.info)
        chn.close()
        return info

    def _get_camera_infos(self, nodes):
        cameras_t = {}
        for node in nodes:
            phy_path = node["phy_path"]
            key = (phy_path.get("pci", None),
                   phy_path.get("usb", None))

            if key not in cameras_t.keys():
                cam_path: dict = deepcopy(node["phy_path"])
                cam_path.pop("chn")
                cam_path.pop("str")
                cam_path["str"] = _repack_v4l_path_parts(cam_path, compact=True)
                cameras_t[key] = {
                    'card': node["card"],
                    'phy_path': cam_path["str"],
                    'stability': node["stability"],
                    'channels': {},
                    'default_capture_channel': None
                }

            # Strip phy path structure details
            node["phy_path"] = phy_path["str"]
            cameras_t[key]["channels"][phy_path.get('chn', 0)] = node

        cameras = {}
        for camera in cameras_t.values():
            for idx, channel in camera["channels"].items():
                if 'VIDEO_CAPTURE' in channel["device_capabilities"]:
                    alias = self._get_alias(camera["phy_path"]) or channel["alias"]
                    cameras[alias] = camera
                    cameras[alias]["default_capture_channel"] = idx
                    break

        # Apply configuration
        cameras_config = self.actual.cameras_config
        default_camera_config = cameras_config["default"]

        for alias, spec in cameras.items():
            cam_config = deepcopy(default_camera_config)

            if alias in cameras_config.keys():
                cam_overrides = cameras_config[alias]
                cam_config = merge_dicts(cam_config, cam_overrides)

            for chn_spec in spec["channels"].values():
                if 'VIDEO_CAPTURE' not in chn_spec["device_capabilities"]:
                    continue

                chn_config = deepcopy(cam_config)
                chn_alias = chn_spec["alias"]

                if chn_alias in cameras_config.keys():
                    chn_overrides = cameras_config[chn_alias]
                    chn_config = merge_dicts(chn_config, chn_overrides)

                chn_spec["config"] = chn_config

                # When camera_inherit_alias is specified, it is assumed that
                #   - there is only one capture channel we care about
                #   - if there are more than one capture channels, the
                #     default_capture_channel is the one we care about
                #   - channel specific config overrides are not present. camera
                #     specific configuration will apply to all channels.
                #   - the camera alias is provided to the capture channel
                #   - the alias configured here is only used for cosmetic
                #     reasons, such as preview display etc.
                if self._inherit_alias:
                    chn_spec["alias"] = alias

        return cameras

    @staticmethod
    def supported():
        # Whether cameras are basically supported, ie, the
        # core dependencies are installed and importable.
        return CAMERA_SUPPORT

    def _detect(self):
        nodes = self._find_v4l_path_nodes()

        if not nodes:
            return {}

        for node in nodes:
            node.update(self._get_node_info(node['dev_path']))
            node.update({'stability': "path"})

        # Process found nodes
        cameras = self._get_camera_infos(nodes)
        return cameras

    def detected(self):
        if not self.supported():
            return {}
        if not self._detected:
            self._detected = self._detect()
        return self._detected

    def available(self):
        return [x for x, spec in self.detected().items()
                if spec['default_capture_channel'] is not None]

    def available_channels(self):
        pass

    def get(self, camera=None, channel=None):
        if camera is None:
            camera = self.available()[0]

        if not camera or camera not in self.available():
            return None

        camera_spec = self._detected[camera]

        if channel is None:
            channel = camera_spec["default_capture_channel"]

        if channel is None:
            return None

        channel_spec = camera_spec["channels"][channel]
        return channel_spec
