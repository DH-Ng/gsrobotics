import cv2
import numpy as np
import numpy.typing as npt
import platform
import glob
import time
import os
import re
import datetime
import threading
from typing import Optional
from cv2.typing import MatLike

# Keeping your original local imports
from .utilities.logger import log_message
from .utilities.image_processing import crop_and_resize

class Camera:
    def __init__(self, device):
        self.device = device
        self.cap = None

    def open(self) -> None:
        self.release()
        
        # Explicitly set the backend for stability
        # Windows: CAP_DSHOW is generally more stable for UVC cameras
        # Linux: CAP_V4L2 is the standard
        os_name = platform.system()
        backend = cv2.CAP_DSHOW if os_name == "Windows" else cv2.CAP_V4L2
        
        self.cap = cv2.VideoCapture(self.device, backend)

        if not self.cap.isOpened():
            self.release()
            raise RuntimeError(f"Could not open camera device: {self.device}")

    def read_frame(self) -> MatLike:
        if self.cap is None or not self.cap.isOpened():
            raise RuntimeError("Camera is not open.")
    
        for _ in range(3):
            ret, frame = self.cap.read()
            if ret and frame is not None:
                return frame
            time.sleep(0.02) # Reduced sleep for better responsiveness
    
        raise RuntimeError("Failed to read frame from device.")

    def release(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    @staticmethod
    def list_devices() -> dict:
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

    @staticmethod
    def find_cameras_windows(camera_name):
        from pygrabber.dshow_graph import FilterGraph
        graph = FilterGraph()
        allcams = graph.get_input_devices()
        description = ""
        for cam in allcams:
            if camera_name in cam:
                description = cam

        try:
            device = allcams.index(description)
        except ValueError:
            log_message(f"Device {camera_name} not found in list: {allcams}")
            return None, None

        return (device, description)


class GelSightMini:
    def __init__(
        self,
        target_width: int = 320,
        target_height: int = 240,
        border_fraction: float = 0.15,
    ):
        self.camera: Camera = None
        self.recording: bool = False
        self.record_filepath: str = None
        self.frame_count: int = 0
        self.time_prev: float = time.time()
        self.fps: float = 0
        self.current_frame: MatLike = None
        self.target_width: int = target_width
        self.target_height: int = target_height
        self.border_fraction: float = border_fraction
        self.video_writer = None
        self.serial_number = None
        self._device_idx = None
        self._device_selected = False

        # Background image of sensor -> tactile RGB image without contact
        self.background_img: MatLike | None = None

        # THREADING IMPROVEMENTS
        self._running = False
        self._capture_thread = None
        self._frame_lock = threading.Lock()
        self._latest_raw_frame = None

    def get_device_list(self) -> dict:
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
                        if device_id is not None and desc:
                            match = re.search(r"[A-Z0-9]{4}-[A-Z0-9]{4}", desc)
                            if match:
                                self.serial_number = match.group()

                elif os_name == "Linux":
                    index = 0 if device_idx is None else device_idx
                    devices = Camera.list_devices()
                    if index not in devices:
                        raise RuntimeError(f"No camera at index {index}.")
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
                
                log_message(f"Camera opened successfully on attempt {attempt}/{max_attempts}.")
                return

            except Exception as e:
                last_error = e
                if candidate:
                    candidate.release()
                self.camera = None
                log_message(f"Camera open attempt {attempt}/{max_attempts} failed: {e}")
                if attempt < max_attempts:
                    time.sleep(retry_delay)

        raise RuntimeError(f"Could not connect to camera after {max_attempts} attempts.") from last_error
    
    def _reconnect_camera(self) -> None:
        log_message("Attempting to reconnect camera...")
        # IMPROVEMENT: Give the OS/USB bus significant time to release the handle
        if self.camera:
            self.camera.release()
        
        time.sleep(2.0) 
        try:
            self.select_device(self._device_idx, max_attempts=3, retry_delay=2.0)
        except Exception as e:
            log_message(f"Reconnection failed: {e}")

    def _capture_loop(self):
        """ Background thread to keep the USB buffer clear and capture latest frames. """
        last_frame_time = time.time() # Add this line
        
        while self._running:
            if self.camera is not None:
                try:
                    frame = self.camera.read_frame()
                    
                    # --- FPS CALCULATION ---
                    now = time.time()
                    dt = now - last_frame_time
                    if dt > 0:
                        self.fps = 1.0 / dt
                    last_frame_time = now
                    # -----------------------
                    
                    with self._frame_lock:
                        self._latest_raw_frame = frame
                except Exception as e:
                    log_message(f"Capture loop read error: {e}")
                    self._reconnect_camera()
                    time.sleep(1.0)
            else:
                time.sleep(0.1)

    def start(self) -> None:
        if not self.camera:
            log_message("Please select a device first!")
            return
        
        self.recording = False  
        
        # Flush initial black frames
        print("Starting camera stream.")
        for _ in range(10):
            try:
                self.camera.read_frame()
            except:
                pass

        raw_frame = self.camera.read_frame()
        self.background_img = cv2.cvtColor(raw_frame, cv2.COLOR_BGR2RGB)
        self.background_img = crop_and_resize(
            image=self.background_img,
            target_size=(self.target_width, self.target_height),
            border_fraction=self.border_fraction,
        )
        # cv2.imshow("bg img ",  cv2.cvtColor(self.background_img, cv2.COLOR_RGB2BGR))

        # IMPROVEMENT: Start the background capture thread
        self._running = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()
        self.frame_count = 0

    def stop(self) -> None:
        """ Stop the capture thread and release resources. """
        self._running = False
        if self._capture_thread:
            self._capture_thread.join(timeout=1.0)
        if self.camera:
            self.camera.release()

    def start_recording(self, filepath: str = None) -> None:
        if not self.camera:
            log_message("Please select a device first!")
            return

        if filepath is None or not os.path.isdir(filepath):
            filepath = self.create_folder()

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(filepath, f"recording_{timestamp}.mp4")

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
        self.recording = False
        if self.video_writer is not None:
            self.video_writer.release()
            self.video_writer = None
            log_message(f"Recording saved to {self.record_filepath}")
            self.record_filepath = None

    def update(self, dt: float) -> Optional[MatLike]:
        if not self._device_selected:
            return None

        with self._frame_lock:
            raw_frame = self._latest_raw_frame
        
        if raw_frame is None:
            if self.camera is None:
                self._reconnect_camera()
            return None

        # REMOVE the FPS calculation lines from here! 
        # (Delete time_now, dt, self.fps = 1.0 / dt, etc.)

        self.current_frame = cv2.cvtColor(raw_frame, cv2.COLOR_BGR2RGB)
        self.frame_count += 1
        self.current_frame = crop_and_resize(
            image=self.current_frame,
            target_size=(self.target_width, self.target_height),
            border_fraction=self.border_fraction,
        )

        if self.recording and self.video_writer is not None:
            self.video_writer.write(cv2.cvtColor(self.current_frame, cv2.COLOR_RGB2BGR))

        return self.current_frame

    def create_folder(self) -> str:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        folder_name = datetime.datetime.now().strftime("%Y-%m-%d")
        folder_path = os.path.join(desktop, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        return folder_path

    def save_screenshot(self, filepath: str = None) -> bool:
        if filepath is None or self.current_frame is None:
            return False

        now = datetime.datetime.now()
        filename = os.path.join(
            filepath, f"screenshot_{now.strftime('%Y%m%d_%H%M%S')}.png"
        )

        try:
            cv2.imwrite(
                filename,
                cv2.cvtColor(self.current_frame, cv2.COLOR_RGB2BGR),
            )
            log_message(f"Screenshot saved to {filename}")
            return True
        except Exception as e:
            log_message(f"Failed to save image: {e}")
            return False
