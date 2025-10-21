

from twisted import logger


class CameraControllerBase(object):
    name = 'base'

    def __init__(self, alias, cam_spec, config):
        self._log = None

        self._config = config
        self._spec = cam_spec
        self._alias = alias or cam_spec.get('alias')

        self._frame_spec_still = None
        self._frame_spec_preview = None

        if hasattr(config, 'camera_preview_show_crop'):
            self._preview_overlay_crop = config.camera_preview_show_crop
        if hasattr(config, 'camera_preview_apply_crop'):
            self._preview_apply_crop = config.camera_preview_apply_crop
        
        self._effective_crop_geometry = {}
        self._preview_crop_geometry = {}

    @property
    def log(self):
        if not self._log:
            self._log = logger.Logger(namespace=f"cam.{self.alias}", source=self)
        return self._log

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

    def exit_wait(self):
        pass

    @property
    def preview_running(self):
        raise NotImplementedError()

    @property
    def errored(self):
        raise NotImplementedError()

    def clear_error(self):
        raise NotImplementedError()

    @property
    def preview_overlay_crop(self):
        return self._preview_overlay_crop

    @preview_overlay_crop.setter
    def preview_overlay_crop(self, value):
        self._preview_overlay_crop = value

    @property
    def preview_apply_crop(self):
        return self._preview_apply_crop

    @preview_apply_crop.setter
    def preview_apply_crop(self, value):
        self._preview_apply_crop = value

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
        if self.spec["config"]["acquire"]["resolution"] != "max":
            res = self.spec["config"]["acquire"]["resolution"]
            w, h = res.strip().split("x")
            return {
                "dev_path": self._spec.get("dev_path", None),
                "width": w, "height": h,
            }

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
        if not self.config.camera_preview_lowres:
            return self._calc_frame_spec_still()

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
        self.log.info(f"Starting Preview")

    def preview_stop(self):
        self.log.info(f"Stopping Preview")

    def get_preview_frame(self, timeout=1.0):
        self.log.debug(f"Getting Preview Frame")

    def capture_still(self, delay=3, output_dir: str = None, on_progress=None):
        self.log.info(f"Capturing Still")

    def effective_crop_geometry(self, pipeline='still'):
        if pipeline not in self._effective_crop_geometry.keys():
            geom = [0, 1, 0, 1]
            pl = self.spec['config']['pipelines'][pipeline]
            for step in pl:
                scfg = self.spec['config'][step]
                if scfg['type'] != 'crop':
                    continue

                cx1, cx2, cy1, cy2 = scfg['x1'], scfg['x2'], scfg['y1'], scfg['y2']

                # Apply crop relative to previous result
                old_x1, old_x2, old_y1, old_y2 = geom

                new_x1 = old_x1 + (old_x2 - old_x1) * cx1
                new_x2 = old_x1 + (old_x2 - old_x1) * cx2
                new_y1 = old_y1 + (old_y2 - old_y1) * cy1
                new_y2 = old_y1 + (old_y2 - old_y1) * cy2

                geom = [new_x1, new_x2, new_y1, new_y2]
            self._effective_crop_geometry[pipeline] = geom
        return self._effective_crop_geometry[pipeline]

    def preview_crop_geometry(self, pipeline='still'):
        """
        Compute and cache the effective 4:3 crop rectangle for the given pipeline.
        The math is done in an isotropic normalized space that preserves aspect ratio,
        so results remain dimensionless but correct for non-square frames.

        TODO Don't understand this, but it seems to work. See
         https://chatgpt.com/c/68f0395e-6ca8-8323-b131-193244a58caa
        """
        if not hasattr(self, "_preview_crop_geometry"):
            self._preview_crop_geometry = {}

        if pipeline in self._preview_crop_geometry:
            return self._preview_crop_geometry[pipeline]

        # Default: full frame
        geom = [0.0, 1.0, 0.0, 1.0]

        x1, x2, y1, y2 = self.effective_crop_geometry(pipeline)
        if (x1, y1, x2, y2) == (0, 0, 1, 1):
            self._preview_crop_geometry[pipeline] = geom
            return geom

        # Need frame aspect ratio, but maybe it'll come later?
        if self._last_preview_frame is None:
            return geom

        h, w = self._last_preview_frame.shape[:2]
        frame_aspect = w / h
        target_aspect = 4 / 3

        # --- Step 1: convert to isotropic normalized space ---
        # Scale X by aspect ratio so 1.0 in X and Y represent equal lengths
        sx1, sx2 = x1 * frame_aspect, x2 * frame_aspect
        sy1, sy2 = y1, y2

        crop_w = sx2 - sx1
        crop_h = sy2 - sy1
        if crop_w <= 0 or crop_h <= 0:
            self._preview_crop_geometry[pipeline] = geom
            return geom

        # --- Step 2: expand to 4:3 while containing the user crop ---
        cx = (sx1 + sx2) / 2
        cy = (sy1 + sy2) / 2
        current_aspect = crop_w / crop_h

        if current_aspect > target_aspect:
            # too wide → expand vertically
            new_h = crop_w / target_aspect
            new_w = crop_w
        else:
            # too tall → expand horizontally
            new_w = crop_h * target_aspect
            new_h = crop_h

        nx1 = cx - new_w / 2
        nx2 = cx + new_w / 2
        ny1 = cy - new_h / 2
        ny2 = cy + new_h / 2

        # --- Step 3: clamp to [0, frame_aspect] × [0,1] ---
        if nx1 < 0:
            nx2 -= nx1
            nx1 = 0
        elif nx2 > frame_aspect:
            shift = nx2 - frame_aspect
            nx1 -= shift
            nx2 -= shift

        if ny1 < 0:
            ny2 -= ny1
            ny1 = 0
        elif ny2 > 1:
            shift = ny2 - 1
            ny1 -= shift
            ny2 -= shift

        # --- Step 4: scale back to standard [0,1] normalized space ---
        nx1 /= frame_aspect
        nx2 /= frame_aspect

        geom = [nx1, nx2, ny1, ny2]
        self._preview_crop_geometry[pipeline] = geom
        return geom

    # TODO
    #  Might want to add an interface like:
    #  - grab_still
    #  - retrieve_still
    #  This will be needed te reduce (but not remove) time difference between images
