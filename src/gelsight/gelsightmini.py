import cv2
import platform
import glob
import time
from cv2.typing import MatLike
import os
import re
import datetime
from typing import Optional
from .utilities.logger import log_message
from .utilities.image_processing import crop_and_resize


class Camera:
    def __init__(self, device):
        """
        Initialize the Camera instance.

        Args:
            device: A numeric index (for Windows/macOS) or device path (for Linux).
        """
        self.device = device
        self.cap = None

    def open(self) -> None:
        self.release()
        self.cap = cv2.VideoCapture(self.device)

        if not self.cap.isOpened():
            self.release()
            raise RuntimeError(f"Could not open camera device: {self.device}")
    

    def read_frame(self) -> MatLike:
        if self.cap is None or not self.cap.isOpened():
            raise RuntimeError("Camera is not open.")
    
        # Retry brief/transient read failures before treating the device as disconnected.
        for _ in range(3):
            ret, frame = self.cap.read()
            if ret and frame is not None:
                return frame
            time.sleep(0.05)
    
        raise RuntimeError("Failed to read frame from device.")

    def release(self) -> None:
        """
        Release the camera resource.
        """
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    @staticmethod
    def list_devices() -> dict:
        """
        Enumerate available camera devices.

        On Linux, returns unique device paths from /dev/v4l/by-id/.
        On Windows/macOS, tests numeric indices 0..5.

        Returns:
            dict: A mapping from index to device identifier.
        """
        devices = {}
        os_name = platform.system()
        if os_name == "Linux":
            paths = glob.glob("/dev/v4l/by-id/*")
            for idx, path in enumerate(paths):
                devices[idx] = path
        else:
            for idx in range(6):
                cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    devices[idx] = f"Camera {idx}"
                    cap.release()
        return devices

    def find_cameras_windows(camera_name):
        from pygrabber.dshow_graph import FilterGraph

        graph = FilterGraph()

        # get the device name
        allcams = graph.get_input_devices()  # list of camera device
        description = ""
        for cam in allcams:
            if camera_name in cam:
                description = cam

        try:
            device = graph.get_input_devices().index(description)
        except ValueError as e:
            print("Device is not in this list")
            print(graph.get_input_devices())
            import sys

            sys.exit()

        return (device, description)


class GelSightMini:
    def __init__(
        self,
        target_width: int = 320,
        target_height: int = 240,
        border_fraction: float = 0.15,
    ):
        """
        Initialize the CameraStream.

        Args:
            target_width (int, optional): Desired width of the camera feed. Defaults to 320.
            target_height (int, optional): Desired height of the camera feed. Defaults to 240.
            border_fraction: (float, optional): Desired border size for the image crop Defaults to 15%.
        """
        self.camera: Camera = None
        self.recording: bool = False
        self.record_filepath: str = None
        self.frame_count: int = 0
        self.time_prev: float = time.time()
        self.fps: float = 0
        self.current_frame_rgb: MatLike = None
        self.current_frame: MatLike = None
        self.target_width: int = target_width
        self.target_height: int = target_height
        self.border_fraction: float = border_fraction
        self.video_writer = None
        self.serial_number = None

        self._device_idx = None
        self._device_selected = False
        self._last_reconnect_time = 0.0


    def get_device_list(self) -> dict:
        """
        Get a dictionary of available camera devices.

        Returns:
            dict: Mapping of device indices to device identifiers.
        """
        return Camera.list_devices()

    def select_device(
        self,
        device_idx=None,
        max_attempts=5,
        retry_delay=1.0,
    ) -> None:
        self._device_idx = device_idx
        self._device_selected = False

        if self.camera is not None:
            self.camera.release()
        self.camera = None

        last_error = None

        for attempt in range(1, max_attempts + 1):
            candidate = None

            try:
                os_name = platform.system()
                device_id = device_idx

                if os_name == "Windows":
                    if device_idx is None:
                        device_id, desc = Camera.find_cameras_windows("GelSight Mini")
                        match = re.search(r"[A-Z0-9]{4}-[A-Z0-9]{4}", desc)
                        if match:
                            self.serial_number = match.group()

                elif os_name == "Linux":
                    index = 0 if device_idx is None else device_idx
                    devices = Camera.list_devices()

                    if index not in devices:
                        raise RuntimeError(
                            f"No camera at index {index}. Available devices: {devices}"
                        )

                    device_id = devices[index]

                elif device_id is None:
                    device_id = 0

                if device_id is None:
                    raise RuntimeError("Resolved camera device is None.")

                candidate = Camera(device=device_id)
                candidate.open()

                candidate.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.target_width)
                candidate.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.target_height)

                self.camera = candidate
                self._device_selected = True

                width = candidate.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                height = candidate.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                log_message(
                    f"Camera opened successfully with resolution {width}x{height} "
                    f"(attempt {attempt}/{max_attempts})."
                )
                return

            except Exception as e:
                last_error = e
                if candidate is not None:
                    candidate.release()

                self.camera = None
                log_message(
                    f"Camera open attempt {attempt}/{max_attempts} failed: {e}"
                )

                if attempt < max_attempts:
                    time.sleep(retry_delay)

        raise RuntimeError(
            f"Could not connect to camera after {max_attempts} attempts."
        ) from last_error
    
    def _reconnect_camera(self) -> None:
        log_message("Attempting to reconnect camera...")
        time.sleep(0.5)
        self.select_device(
            self._device_idx,
            max_attempts=5,
            retry_delay=1.0,
        )
    
    def start(self) -> None:
        """
        Start the camera stream.
        """
        if not self.camera:
            log_message("Please select a device first!")
            return
        self.recording = False  

        # flush black frames
        print("Starting camera stream.")
        for _ in range(20):
            try:
                self.camera.read_frame()
            except RuntimeError as e:
                log_message(f"Camera read failed during startup: {e}")
                self._reconnect_camera()
                break
        
        self.frame_count = 0

    def start_recording(self, filepath: str = None) -> None:
        """
        Start recording the camera feed to a video file.

        Args:
            filepath (str, optional): Directory path to save the recording. If not provided or invalid,
                a default folder is created.
        """
        if not self.camera:
            log_message("Please select a device first!")
            return

        if filepath is None or not os.path.isdir(filepath):
            filepath = self.create_folder()

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(filepath, f"recording_{timestamp}.mp4")

        if not filepath:
            log_message("Error: File path is empty!")
            return

        fps = self.fps if self.fps > 0 else 30

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self.video_writer = cv2.VideoWriter(
            filepath, fourcc, fps, (self.target_width, self.target_height)
        )
        self.record_filepath = filepath

        self.recording = True
        self.frame_count = 0
        log_message(f"Started recording to {filepath}")

    def stop_recording(self) -> None:
        """
        Stop recording the camera feed.
        """
        self.recording = False
        if self.video_writer is not None:
            self.video_writer.release()
            self.video_writer = None
            log_message(f"Recording saved to {self.record_filepath}")
            self.record_filepath = None

    def update(self, dt: float) -> Optional[MatLike]:
        """
        Capture and return a frame from the camera feed, update FPS, overlay FPS text, and record if enabled.

        Args:
            dt (float): Unused parameter; frame timing is computed internally.

        Returns:
            Optional[MatLike]: The current RGB frame with FPS overlay, or None on error.
        """
        if not self._device_selected:
            return None

        if self.camera is None:
            self._reconnect_camera()
            if self.camera is None:
                return None

        try:
            frame = self.camera.read_frame()
        except Exception as e:
            log_message(f"Error reading frame: {e}")
            self._reconnect_camera()
            return None

        time_now = time.time()
        dt = time_now - self.time_prev
        self.fps = 1.0 / dt if dt > 0 else 0
        self.time_prev = time_now

        self.current_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        self.frame_count += 1
        self.current_frame = crop_and_resize(
            image=self.current_frame,
            target_size=(self.target_width, self.target_height),
            border_fraction=self.border_fraction,
        )

        if self.recording and self.video_writer is not None:
            # Convert color back to BGR
            self.video_writer.write(cv2.cvtColor(self.current_frame, cv2.COLOR_RGB2BGR))

        return self.current_frame

    def create_folder(self) -> str:
        """
        Create a folder on the Desktop named with the current date.

        Returns:
            str: The created folder path.
        """
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        folder_name = datetime.datetime.now().strftime("%Y-%m-%d")
        folder_path = os.path.join(desktop, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        return folder_path

    def save_screenshot(self, filepath: str = None) -> bool:
        """
        Save a screenshot of the current frame.

        Args:
            filepath (str, optional): Directory path to save the screenshot.

        Returns:
            bool: True if saving succeeded, False otherwise.
        """
        saved = False
        if filepath is None:
            return saved

        if self.current_frame is not None:
            now = datetime.datetime.now()
            filename = os.path.join(
                filepath, f"screenshot_{now.strftime('%Y%m%d_%H%M%S')}.png"
            )

            try:
                cv2.imwrite(
                    filename,
                    cv2.cvtColor(self.current_frame, cv2.COLOR_RGB2BGR),
                )
                saved = True
                log_message(f"Screenshot saved to {filename}")
            except Exception as e:
                log_message(f"Failed to save image: {e}")

        return saved
