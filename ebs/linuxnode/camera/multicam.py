

from twisted.internet.defer import inlineCallbacks, gatherResults
from .controllers.opencv import CameraControllerOpenCV


class MultiCameraManager(object):
    def __init__(self, actual, backend='opencv'):
        self._actual = actual
        self._backend = backend
        self._cameras = {}
        self.install()

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
        return self._cameras.values()

    def get(self, alias):
        return self._cameras[alias]

    @inlineCallbacks
    def preview_start_all(self):
        pass

    @inlineCallbacks
    def preview_stop_all(self):
        pass

    @inlineCallbacks
    def capture_still(self, alias, output_dir=None):
        camera = self._cameras[alias]
        out_path = yield camera.capture_still(output_dir=output_dir)
        return out_path

    @inlineCallbacks
    def capture_still_all(self, batch_size=2, output_dir=None):
        results = []

        for i in range(0, len(self.aliases), batch_size):
            batch = list(self.aliases)[i:i + batch_size]
            ds = []
            # Start all still captures in this batch
            for alias in batch:
                camera = self._cameras[alias]
                d = camera.capture_still(output_dir=output_dir)
                ds.append(d)
            try:
                res = yield gatherResults(ds)
                results.extend(res)
            except Exception as e:
                print(f"Batch {i // batch_size} failed: {e}")

        return results

    def install(self):
        # TODO This should be capture channels instead?
        # Presently this only installs the default capture channel for each physical camera
        self._cameras = {
            x: self.controller_cls(x, self.actual.sysinfo.cameras.get(x), self.actual.config)
            for x in self.actual.sysinfo.cameras.available()
        }
