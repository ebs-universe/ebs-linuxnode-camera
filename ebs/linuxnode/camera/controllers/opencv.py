

import os
import cv2
import time
import threading
from copy import copy
from datetime import datetime, timezone

from twisted.internet import reactor
from twisted.internet import threads
from twisted.internet.defer import inlineCallbacks

from .base import CameraControllerBase
from ..utils import dict_to_ns


class CameraControllerOpenCV(CameraControllerBase):
    def __init__(self, alias, cam_spec: dict, config):
        super().__init__(alias, cam_spec, config)
        self._lock = threading.Lock()

        # Preview state
        self._preview_thread = None
        self._preview_cap = None
        self._last_preview_frame = None

        self._preview_running = threading.Event()
        self._frame_cond = threading.Condition()  # notify new frame

    def _preview_loop(self, dev, w, h):
        cap = cv2.VideoCapture(dev)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # cap.set(cv2.CAP_PROP_FPS, fps)

        if not cap.isOpened():
            self._lock.release()
            raise RuntimeError("Failed to open camera for preview")

        # actual_fps = cap.get(cv2.CAP_PROP_FPS)
        # print(f"Desired FPS: {fps}, Actual FPS: {actual_fps}")

        self._preview_cap = cap
        self._preview_running.set()

        while self._preview_running.is_set():
            ret, frame = cap.read()
            if not ret:
                continue  # skip bad frame
            with self._frame_cond:
                self._last_preview_frame = frame
                self._frame_cond.notify_all()

        cap.release()
        self._preview_cap = None
        self._lock.release()

    def preview_start(self):
        """
        Start preview in a dedicated thread.
        Returns a Deferred that fires when the thread is running.
        """
        def _start():
            if self._preview_running.is_set():
                return
            if not self._lock.acquire(blocking=False):
                raise RuntimeError("Camera is already in use")

            spec = self.frame_spec_preview
            self._preview_thread = threading.Thread(
                target=self._preview_loop,
                args=(spec["dev_path"], spec["width"], spec["height"]),
                daemon=True,
            )
            self._preview_thread.start()

            # Wait until preview loop signals it's running
            while not self._preview_running.is_set():
                time.sleep(0.1)

        return threads.deferToThread(_start)

    def preview_stop(self):
        """
        Stop preview and wait for thread to exit.
        """
        def _stop():
            if not self._preview_running.is_set():
                return
            self._preview_running.clear()
            if self._preview_thread:
                self._preview_thread.join(timeout=1.0)
                self._preview_thread = None

        return threads.deferToThread(_stop)

    def get_preview_frame(self, timeout=1.0):
        def _get():
            if not self._preview_running.is_set():
                raise RuntimeError("Preview is not running")

            end_time = time.time() + timeout
            with self._frame_cond:
                if self._last_preview_frame is None:
                    while (
                            self._last_preview_frame is None
                            and time.time() < end_time
                    ):
                        remaining = end_time - time.time()
                        if remaining <= 0:
                            break
                        self._frame_cond.wait(timeout=remaining)

                if self._last_preview_frame is None:
                    raise RuntimeError("Timed out waiting for preview frame")

                return self._last_preview_frame
        return threads.deferToThread(_get)

    @inlineCallbacks
    def capture_still(self, output_dir: str = None, on_progress=None):
        """
        Capture stills safely: only one capture at a time per camera.
        """
        if self._preview_running.is_set():
            yield self.preview_stop()

        def _report_progress_from_thread(progress):
            if on_progress:
                reactor.callFromThread(on_progress, progress)

        def _do_capture_locked():
            with self._lock:  # ensure only one thread uses the device
                return self._do_capture_still(output_dir, _report_progress_from_thread)

        result = yield threads.deferToThread(_do_capture_locked)
        return result

    def _pl_connect(self, spec, **context):
        frame_spec = self.frame_spec_still
        cap = cv2.VideoCapture(frame_spec["dev_path"], cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_spec["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_spec["height"])
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            cap.release()
            raise RuntimeError("Failed to open camera for still capture")

        context['cap'] = cap
        return context

    def _pl_acquire(self, spec, **context):
        time.sleep(spec.delay)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
        # TODO Might need to grab old frames or so here?
        cap = context.pop("cap")
        r, frame = cap.read()
        if not r:
            raise RuntimeError(f"Camera {self._alias} Could not read frame")
        cap.release()
        context['ts'] = ts
        context['frame'] = frame
        return context

    def _pl_crop(self, spec, **context):
        frame = context.pop("frame")
        if (spec.x1, spec.y1, spec.x2, spec.y2) != (0, 0, 1, 1):
            y, x, l = frame.shape
            y1 = int(spec.y1 * y)
            y2 = int(spec.y2 * y)
            x1 = int(spec.x1 * x)
            x2 = int(spec.x2 * x)
            context['frame'] = frame[y1:y2, x1:x2]
        else:
            context['frame'] = frame
        return context

    def _pl_denoise(self, spec, **context):
        if spec.method != "nlm":
            raise NotImplementedError("Only nlm denoising is supported")
        frame = context.pop("frame")
        dst = cv2.fastNlMeansDenoisingColored(
            frame, None,
            spec.params.h, spec.params.hcolor,
            spec.params.template_window_size,
            spec.params.search_window_size
        )
        context['frame'] = dst
        return context

    def _pl_save(self, spec, **context):
        # TODO Might want to add jpeg / mjpeg support?
        ext = spec.format
        if ext != "png":
            raise NotImplementedError("Only png supported")

        ts = context.pop("ts")
        out_name = f"capture_{self._alias}_{ts}.{ext}"

        if spec.compression:
            params = [cv2.IMWRITE_PNG_COMPRESSION, spec.compression]
        else:
            params = None

        output_dir = context.pop("output_dir", None)
        if output_dir:
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
            out_path = os.path.join(output_dir, out_name)
        else:
            out_path = out_name

        context['out_path'] = out_path
        cv2.imwrite(out_path, context['frame'], params)
        return context

    def _do_capture_still(self, output_dir, report_progress):
        """
        Asynchronously capture a single still at max resolution.
        Returns (filename, image_bytes).
        """
        cfg = dict_to_ns(self._spec["config"])
        pipeline = cfg.pipelines.still

        if pipeline[0] != 'acquire':
            raise RuntimeError('Still capture pipelines must start with "acquire"')

        # Insert camera open step
        pipeline.insert(0, 'connect')

        # Custom handling for the open_camera step
        def _special_connect(cfg):
            sp = copy(cfg.acquire)
            if hasattr(sp, "type"):
                del sp.type
            return sp

        context = self._execute_pipeline(
            cfg=cfg,
            pipeline=pipeline,
            initial_context={'output_dir': output_dir},
            report_progress=report_progress,
            special_steps={'connect': _special_connect},
        )

        return context['out_path']
