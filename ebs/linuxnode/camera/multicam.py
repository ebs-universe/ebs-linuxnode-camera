

import os
from twisted import logger
from twisted.internet.defer import inlineCallbacks, gatherResults, succeed, Deferred
from .controllers.opencv import CameraControllerOpenCV


class MultiCameraManager(object):
    def __init__(self, actual, batch_size=2, backend='opencv'):
        self._log = None
        self._actual = actual
        self._backend = backend
        self._batch_size = batch_size
        self._cameras = {}
        self.install()

    @property
    def log(self):
        if not self._log:
            self._log = logger.Logger(namespace="cam.multi", source=self)
        return self._log

    @property
    def actual(self):
        return self._actual

    @property
    def controller_cls(self):
        # TODO Consider adding support for the following backends
        #  - (done) opencv
        #  - pygame
        #  - picamera2  (RPi)
        #  - libcamera  (RPi, Other hosts unclear)
        #  - linuxpy + v4l2
        #  - gstreamer with any of the above (?)
        if self._backend == 'opencv':
            return CameraControllerOpenCV
        else:
            raise NotImplementedError()

    @property
    def aliases(self):
        # TODO This should return capture channels instead?
        return self._cameras.keys()

    def get(self, alias):
        return self._cameras[alias]

    @inlineCallbacks
    def preview_start(self, aliases=None):
        if aliases is None:
            aliases = self.aliases
        ds = []
        for alias in aliases:
            d = self._cameras[alias].preview_start()
            ds.append(d)
        try:
            res = yield gatherResults(ds)
            return res
        except Exception as e:
            self.log.error(f"Preview Start Failed: {e}")

    @inlineCallbacks
    def preview_stop(self, aliases=None):
        if aliases is None:
            aliases = self.aliases
        ds = []
        for alias in aliases:
            d = self._cameras[alias].preview_stop()
            ds.append(d)
        try:
            res = yield gatherResults(ds)
            return res
        except Exception as e:
            self.log.error(f"Preview Stop Failed: {e}")

    def _ensure_output_dir(self, output_dir):
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except OSError as e:
                self.log.error(f"Error: Could not create output directory '{output_dir}': {e}")
                raise

        if not os.path.isdir(output_dir):
            msg = f"Path exists but is not a directory: '{output_dir}'"
            self.log.error(msg)
            raise NotADirectoryError(msg)

        test_file = os.path.join(output_dir, '.write_test')
        try:
            with open(test_file, 'w') as f:
                f.write('')
            os.remove(test_file)
        except PermissionError:
            msg = f"Directory exists but is not writable: '{output_dir}'"
            self.log.error(msg)
            raise PermissionError(msg)
        except OSError as e:
            msg = f"Unhandled Error writing to directory: '{output_dir}' : {e}"
            self.log.error(msg)
            raise OSError(msg)
        return True

    @inlineCallbacks
    def capture_still(self, aliases=None, output_dir=None,
                      on_progress=None,
                      handler=None, handler_name=None):
        active_connect_or_acquire = set()
        waiting_cameras = []

        if not output_dir:
            output_dir = self.actual.config.camera_capture_path

        if output_dir:
            try:
                self._ensure_output_dir(output_dir)
            except Exception as e:
                self.log.error("Problem with Output Dir. Not writing output!")
                output_dir = None

        if aliases is None:
            aliases = self.aliases

        if len(aliases) == 1:
            camera = self._cameras[aliases[0]]
            outpath = yield camera.capture_still(output_dir=output_dir, on_progress=on_progress)
            if handler:
                yield handler(outpath)
            return [outpath]

        def _progress_handler(progress):
            key = progress['key']
            current = progress["current"]

            if current in ("connect", "acquire"):
                active_connect_or_acquire.add(key)
            elif key in active_connect_or_acquire and \
                    current not in ("connect", "acquire"):
                active_connect_or_acquire.discard(key)
                if waiting_cameras:
                    alias_next, d_next = waiting_cameras.pop(0)
                    if not d_next.called:
                        d_next.callback(None)

            # Modify progress to accomodate handler
            if handler:
                if progress["done"] == progress["max"]:
                    progress["current"] = handler_name
                progress["max"] = progress["max"] + 1
                if progress["done"] == progress["max"]:
                    progress["current"] = "done"

            if on_progress:
                on_progress(progress)

        @inlineCallbacks
        def camera_trigger(alias):
            camera = self._cameras[alias]
            if len(active_connect_or_acquire) >= 1:
                d_wait = Deferred()
                waiting_cameras.append((alias, d_wait))
                yield d_wait

            active_connect_or_acquire.add(alias)
            try:
                result = yield camera.capture_still(
                    output_dir=output_dir, on_progress=_progress_handler
                )
                if handler:
                    yield handler(result)
                    if on_progress:
                        on_progress({'key': camera.alias, 'max': 1, 'done': 1, 'current': 'done'})

            except Exception as e:
                self.log.error(f"Camera {alias} Failed: {e}")
                result = None

            return result

        results = []
        ds = [camera_trigger(alias) for alias in aliases]
        try:
            res = yield gatherResults(ds)
            results.extend(res)
        except Exception as e:
            self.log.error(f'Some camera captures failed: {e}')

        return results

    def install(self):
        # TODO This should be capture channels instead?
        # Presently this only installs the default capture channel for each physical camera
        self._cameras = {
            x: self.controller_cls(x, self.actual.sysinfo.cameras.get(x), self.actual.config)
            for x in self.actual.sysinfo.cameras.available()
        }

    def exit_wait(self):
        self.log.info("Stopping Camera Threads")
        for camera in self._cameras.values():
            camera.exit_wait()
