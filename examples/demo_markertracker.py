import os

os.environ["KIVY_NO_ARGS"] = "1"
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.widget import Widget
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.button import Button
from kivy.core.window import Window
from kivy.config import Config
from kivy.metrics import dp
from kivy.graphics.texture import Texture

from gelsight.gelsightmini import GelSightMini
from gelsight.utilities.image_processing import add_fps_count_overlay, rescale
from gelsight.utilities.ui_components import ConnectingOverlay, FileChooserPopup, TopBar
from gelsight.utilities.markerdata_logger import MarkerDataLogger
from gelsight.utilities.logger import log_message
from gelsight.config import ConfigModel
import cv2
import numpy as np
from gelsight.marker_tracker import MarkerTracker

Config.set("input", "mouse", "mouse,multitouch_on_demand")


class GelsightMini(App):
    def __init__(self, config: ConfigModel, **kwargs):
        super().__init__(**kwargs)

        self.config = config
        self.cam_stream = GelSightMini(
            target_width=self.config.camera_width,
            target_height=self.config.camera_height,
            border_fraction=self.config.border_fraction,
        )

    def build(self):
        self.title = "Gelsight Marker Tracking"
        self.loading_overlay = None

        root = BoxLayout(orientation="vertical")
        # Top bar with device selection
        self.top_bar = TopBar(on_device_selected_callback=self.restart_camera_stream)
        root.add_widget(self.top_bar)

        # Create MarkerTrackerViewWidget
        self.martertracker_view = MarkerTrackerViewWidget(main_app=self)
        root.add_widget(self.martertracker_view)

        return root

    def show_overlay(self, message):
        if not self.loading_overlay:
            self.loading_overlay = ConnectingOverlay(message=message)
            self.loading_overlay.open()

    def hide_overlay(self):
        if self.loading_overlay:
            self.loading_overlay.dismiss()
            self.loading_overlay = None

    def restart_camera_stream(self, device_index):
        self.cam_stream.select_device(device_index)
        from kivy.clock import Clock

        Clock.schedule_once(lambda dt: self.finish_device_selection(), 0)

    def finish_device_selection(self):
        self.hide_overlay()
        self.martertracker_view.start()


class MarkerTrackerViewWidget(BoxLayout):
    def __init__(self, main_app: GelsightMini, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.main_app = main_app
        self.initialized: bool = False
        self.is_logging_data: bool = False
        self.data_logger: MarkerDataLogger = None
        self.data_folder_path: str = os.path.join(os.path.expanduser("~"), "Desktop")
        # Create UI elements:
        self.image_widget = Image()
        self.add_widget(self.image_widget)

        # Zoom layout
        zoom_layout = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(40)
        )
        zoom_layout.add_widget(
            Label(text="Zoom:", size_hint=(None, None), size=(dp(60), dp(40)))
        )
        self.zoom_slider = Slider(min=0.5, max=3.0, value=1.0)
        self.zoom_slider.bind(value=self.on_zoom_value_change)
        zoom_layout.add_widget(self.zoom_slider)
        self.zoom_label = Label(
            text="1.0x", size_hint=(None, None), size=(dp(60), dp(40))
        )
        zoom_layout.add_widget(self.zoom_label)
        self.add_widget(zoom_layout)

        # Folder selection layout
        folder_layout = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            spacing=dp(80),
            padding=[dp(10)] * 4,
        )
        self.data_folder_btn = Button(
            text="Data Folder", size_hint=(None, None), size=(dp(180), dp(30))
        )
        self.data_folder_btn.bind(on_press=self.open_screenshot_folder_choice)
        folder_layout.add_widget(self.data_folder_btn)
        self.data_folder_label = Label(
            text=f"{os.path.join(os.path.expanduser('~'), 'Desktop')}",
            size_hint=(None, None),
            height=dp(30),
            width=dp(400),
            halign="left",
            valign="middle",
        )
        folder_layout.add_widget(self.data_folder_label)
        self.add_widget(folder_layout)

        # Capture controls layout
        capture_layout = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            spacing=dp(20),
            padding=[dp(10)] * 4,
        )
        self.screenshot_btn = Button(
            text="Save Image", size_hint=(None, None), size=(dp(180), dp(30))
        )
        self.screenshot_btn.bind(on_press=self.take_screenshot)
        capture_layout.add_widget(self.screenshot_btn)

        self.register_data_btn = Button(
            text="Start Recording", size_hint=(None, None), size=(dp(180), dp(30))
        )
        self.register_data_btn.bind(on_press=self.register_data)
        capture_layout.add_widget(self.register_data_btn)

        self.reset_tracking = Button(
            text="Reset Tracking", size_hint=(None, None), size=(dp(180), dp(30))
        )
        self.reset_tracking.bind(on_press=self.on_reset_tracking)
        capture_layout.add_widget(self.reset_tracking)

        self.add_widget(capture_layout)

        self.add_widget(Widget(size_hint_y=None, height=dp(10)))

        self.event = None

        # Bind key events for shortcuts
        Window.bind(on_key_down=self.on_key_down)

    def on_zoom_value_change(self, instance, value):
        self.zoom_label.text = f"{value:.1f}x"

    def on_reset_tracking(self, instance=None):
        self.initialized = False

    def start(self):
        # Start the camera stream and schedule updates.
        self.main_app.cam_stream.start()
        self.initialized = False
        self.event = Clock.schedule_interval(self.update, 1 / 30.0)

    def initialize(self, frame: np.ndarray):
        self.DRAW_MARKERS = False
        self.markertracker = MarkerTracker(frame)I 
        self.data_logger = MarkerDataLogger()

    def update(self, dt):
        frame = self.main_app.cam_stream.update(dt)
        if frame is None:
            return

        if not self.initialized:
            self.initialize(frame=frame)
            self.initialized = True

        else:
            self.update_marker_view(frame=frame)

            scale = self.zoom_slider.value
            if scale != 1.0:
                frame = rescale(frame, scale=scale)

            add_fps_count_overlay(frame=frame, fps=self.main_app.cam_stream.fps)

            texture = Texture.create(
                size=(frame.shape[1], frame.shape[0]), colorfmt="rgb"
            )
            texture.blit_buffer(frame.tobytes(), colorfmt="rgb", bufferfmt="ubyte")
            texture.flip_vertical()
            self.image_widget.texture = texture

    def update_marker_view(self, frame: np.ndarray):
        self.markertracker.track_markers_with_optical_flow(frame)

    def stop(self):
        if self.event:
            self.event.cancel()
        if self.main_app.cam_stream.camera:
            self.main_app.cam_stream.camera.release()

    def take_screenshot(self, instance=None):
        self.main_app.cam_stream.save_screenshot(filepath=self.data_folder_path)

    def register_data(self, instance=None):
        if not self.data_logger:
            return

        if not self.is_logging_data:
            self.is_logging_data = True
            self.register_data_btn.text = "Save Data"
        else:
            self.data_logger.save_data(
                save_csv=True, save_npy=True, folder=self.data_folder_path
            )
            self.is_logging_data = False
            self.register_data_btn.text = "Start Recording"

    def on_key_down(self, window, key, *args):
        # Space key for screenshot
        if key == 32:
            self.take_screenshot()

    def open_screenshot_folder_choice(self, instance):
        popup = FileChooserPopup(self.select_screenshot_folder)
        popup.open()

    def select_screenshot_folder(self, path):
        if path:
            self.data_folder_path = path
            self.data_folder_label.text = f"Target Folder: {self.data_folder_path}"


if __name__ == "__main__":
    import argparse
    from gelsight.config import GSConfig

    parser = argparse.ArgumentParser(
        description="Run the Gelsight Mini Viewer with an optional config file."
    )
    parser.add_argument(
        "--gs-config",
        type=str,
        default=None,
        help="Path to the JSON configuration file. If not provided, default config is used.",
    )

    args = parser.parse_args()

    if args.gs_config is not None:
        log_message(f"Provided config path: {args.gs_config}")
    else:
        log_message(f"Didn't provide custom config path.")
        log_message(
            f"Using default config path './default_config.json' if such file exists."
        )
        log_message(
            f"Using default_config variable from 'config.py' if './default_config.json' is not available"
        )
        args.gs_config = "default_config.json"

    gs_config = GSConfig(args.gs_config)
    GelsightMini(config=gs_config.config).run()
