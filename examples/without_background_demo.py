import cv2
import numpy as np
import datetime
from gelsight.gelsightmini import GelSightMini

FULLWIDTH = 3280
FULLHEIGHT = 2464

# Image size and crop
imgw = 640 
imgh = 480 
brd_frac = 0.15

def show_image():
    counter = 0
    # cam = GelSightMini(target_width=imgw, target_height=imgh, border_fraction=brd_frac)

    cam = GelSightMini(target_width=imgw, target_height=imgh, border_fraction=brd_frac)

    # Note: select_device() does not return a value, it configures the object internally
    cam.select_device()

    start = datetime.datetime.now()

    # Settings for FPS overlay
    org = (50, 50)
    font = cv2.FONT_HERSHEY_SIMPLEX
    fontScale = 1
    color = (255, 255, 255)
    thickness = 2
    nframeavg = 10
    fpsstr = "Calculating..."

    cam.start()
    
    print("Waiting for first frame...")
    while True:
        img = cam.update(1.0)

        if img is not None:
            # Subtract Background image
            abs_diff = cv2.absdiff(img, cam.background_img)
            cv2.imshow("abs_diff", cv2.cvtColor(abs_diff, cv2.COLOR_RGB2BGR))
            
            # img = img - cam.background_img
            img = cv2.subtract(img, cam.background_img)
            
            # Use the FPS calculated inside the GelSightMini class
            fpsstr = f"{cam.fps:.1f} FPS"

            imbgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            cv2.putText(
                imbgr, fpsstr, org, font, fontScale, color, thickness, cv2.LINE_AA
            )
            cv2.imshow("frame_rgb", imbgr)
        else:
            # Optional: print a message if the camera is struggling to provide frames
            # print("Waiting for frame...")
            pass

        if cv2.waitKey(1) == ord("q"):
            end = datetime.datetime.now()
            total_time = end - start
            if counter > 0:
                avg_time = total_time.total_seconds() / counter * 1000
                fps = 1000 / avg_time
                print(f"Avg Time: {avg_time:.2f}ms, Avg FPS: {fps:.2f}")
            break

    cv2.destroyAllWindows()
    cam.stop() # Important to stop the background thread!

if __name__ == "__main__":
    show_image()
