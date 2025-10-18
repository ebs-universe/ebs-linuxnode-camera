

import json
from twisted.internet import reactor, task
from twisted.internet.defer import inlineCallbacks

from ebs.linuxnode.core import config
from ebs.linuxnode.core.basenode import BaseIoTNode

from ebs.linuxnode.camera.mixin import CameraMixin


class ExampleNode(CameraMixin, BaseIoTNode):
    def test_camera_config(self):
        print("Camera Aliases")
        print(self.camera_aliases)

    @inlineCallbacks
    def test_camera_detection(self):
        print("Cameras Detection Test")
        avail = yield self.sysinfo.cameras.available()
        print("Available Cameras:", avail)
        camera_key = 'A'
        print(f"Get Camera Channel: <{camera_key}>")
        cam = yield self.sysinfo.cameras.get(camera_key)
        print(json.dumps(cam, indent=4))

    @inlineCallbacks
    def test_camera_acquisition(self):
        print("Camera Acquisition Test")

        def show_progress(progress):
            print(f"Capture progress: {progress}")

        camera_key = 'A'
        camera = self.cameras.get(camera_key)
        print(camera)
        out_path = yield camera.capture_still(on_progress=show_progress)
        return out_path

    @inlineCallbacks
    def test_camera_preview(self):
        camera_key = 'A'
        camera = self.cameras.get(camera_key)
        print(f"Camera {camera.alias}: Starting Camera Preview")
        yield camera.preview_start()

        @inlineCallbacks
        def fetch_frame():
            try:
                frame = yield camera.get_preview_frame()
                if frame is not None:
                    print(f"Camera {camera_key}: Got preview frame: {frame.shape}")
            except Exception as e:
                print("Error fetching frame:", e)
                yield self._stop_preview(camera)

        self._preview_loop = task.LoopingCall(fetch_frame)
        self._preview_loop.start(0.5, now=True)

        # Stop after 5 seconds for demo purposes
        # reactor.callLater(5, self._stop_preview, camera)

    @inlineCallbacks
    def _stop_preview(self, camera):
        print(f"Camera {camera.alias}: Stopping preview...")
        yield camera.preview_stop()
        if self._preview_loop and self._preview_loop.running:
            self._preview_loop.stop()

    def start(self):
        self.install()
        super(ExampleNode, self).start()
        # self.config.print()
        # reactor.callLater(3, self.test_camera_config)
        # reactor.callLater(5, self.test_camera_detection)
        reactor.callLater(5, self.test_camera_preview)
        reactor.callLater(20, self.test_camera_acquisition)
        reactor.callLater(120, self.stop)
        reactor.run()

    def stop(self):
        super(ExampleNode, self).stop()
        reactor.stop()


def main():
    nodeconfig = config.IoTNodeConfig()
    config.current_config = nodeconfig

    node = ExampleNode(reactor=reactor)
    node.start()


if __name__ == '__main__':
    main()
