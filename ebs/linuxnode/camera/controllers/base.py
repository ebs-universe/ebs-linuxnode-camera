

from .pipeline import PipelineExecutor


class CameraControllerBase(PipelineExecutor):
    name = 'base'

    def __init__(self, alias, cam_spec, config):
        self._config = config
        self._spec = cam_spec
        self._alias = alias or cam_spec.get('alias')

        self._frame_spec_still = None
        self._frame_spec_preview = None

    @property
    def alias(self):
        return self._alias

    @property
    def path(self):
        return self.spec['phy_path']

    @property
    def card(self):
        return self.spec['card']

    @property
    def spec(self):
        return self._spec

    @property
    def config(self):
        return self._config

    @property
    def frame_spec_preview(self):
        if self._frame_spec_preview is None:
            self._frame_spec_preview = self._calc_frame_spec_preview()
        return self._frame_spec_preview

    @property
    def frame_spec_still(self):
        if self._frame_spec_still is None:
            self._frame_spec_still = self._calc_frame_spec_still()
        return self._frame_spec_still

    def _calc_frame_spec_still(self):
        # Find max resolution
        max_width = 0
        max_height = 0
        for fi in self.spec.get("frame_info", []):
            if fi["width"] * fi["height"] > max_width * max_height:
                max_width = fi["width"]
                max_height = fi["height"]

        return {
            "dev_path": self._spec.get("dev_path", None),
            "width": max_width,
            "height": max_height,
        }

    def _calc_frame_spec_preview(self):
        # Find min resolution
        min_width = 10000
        min_height = 10000
        for fi in self.spec.get("frame_info", []):
            if fi["width"] * fi["height"] < min_width * min_height:
                min_width = fi["width"]
                min_height = fi["height"]

        return {
            "dev_path": self.spec.get("dev_path", None),
            "width": min_width,
            "height": min_height,
        }

    def preview_start(self):
        # Return deferred
        raise NotImplementedError()

    def preview_stop(self):
        # Return deferred
        raise NotImplementedError()

    def get_preview_frame(self, timeout=1.0):
        # Return deferred
        raise NotImplementedError()

    def capture_still(self, delay=3, output_dir: str = None):
        # Return deferred
        raise NotImplementedError()

    # TODO
    #  Might want to add an interface like:
    #  - grab_still
    #  - retrieve_still
    #  This will be needed te reduce (but not remove) time difference between images
