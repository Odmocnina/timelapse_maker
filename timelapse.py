import cv2
import os
import argparse
import datetime
import numpy as np
import sys
import ftp_handeler as ftp
from PIL import Image
import io

NOT_FOUND_PARAMETER = -1

"""
    Helper function to safely read watermark image using Pillow (supports GIF and broken PNGs).
    param: path - path to the watermark image
    return: watermark image as a numpy array in BGRA format (or None if error)
"""
def read_watermark_safe(path):
    try:
        with open(path, "rb") as f:
            img_data = f.read()
        pil_img = Image.open(io.BytesIO(img_data)).convert('RGBA')
        numpy_rgba = np.array(pil_img)
        return cv2.cvtColor(numpy_rgba, cv2.COLOR_RGBA2BGRA)
    except Exception as e:
        print(f"Warning: Could not load watermark image '{path}': {e}")
        return None

"""
    Function for reading config for multiple watermark overlays.
    Expected format in config: logo_name=path_to_logo;x_coord;y_coord
    param: config - read config (hashmap)
    return: list of dictionaries containing 'path', 'x', and 'y' for each valid watermark
"""
def get_watermarks(config):
    watermarks = []
    
    # go over all logo items
    for key, value in config.items():
        if key.startswith('logo'):
            parts = value.split(';') # if logo item is found, get all parameters from it
            
            if len(parts) == 3:
                logo_path = parts[0].strip()
                try:
                    logo_x = int(parts[1].strip())
                    logo_y = int(parts[2].strip())
                    
                    # add logo item to watermarks list if coordinates are valid
                    watermarks.append({'path': logo_path, 'x': logo_x, 'y': logo_y})
                    print(f"Found watermark '{key}': {logo_path}, Position: x={logo_x}, y={logo_y}")
                except ValueError: # if something is fucked up with coordinates, skip this logo item
                    print(f"Warning: Invalid coordinates in '{key}' ('{value}'). Skipping this watermark.")
            else:
                print(f"Warning: Invalid format for '{key}' ('{value}'). Expected 'path;x;y'. Skipping.")
                
    return watermarks

"""
    Function to apply all watermarks from the list to the base image.
    param: base_img - the background image (numpy array, 3 channels)
    param: watermarks - list of dictionaries containing 'path', 'x', and 'y' for each watermark
"""
def apply_all_watermarks(base_img, watermarks):
    for wm in watermarks:
        # read the watermark image as bytes to handle special characters in path, then load it with Pillow to ensure we get the alpha channel if it exists
        watermark_img = read_watermark_safe(wm['path'])
        
        if watermark_img is not None:
            base_img = apply_watermark(base_img, watermark_img, wm['x'], wm['y'])
            
    return base_img

"""
    Function to overlay a watermark (with optional transparency) onto a base image.
    param: base_img - the background image (numpy array, 3 channels)
    param: watermark_img - the logo image (numpy array, 3 or 4 channels for transparency)
    param: x - top-left x coordinate
    param: y - top-left y coordinate
"""
def apply_watermark(base_img, watermark_img, x, y):
    if base_img is None or watermark_img is None: # check if images were loaded successfully
        return base_img

    # get dimensions of both images
    h_w, w_w = watermark_img.shape[:2]
    h_b, w_b = base_img.shape[:2]

    # safety check - if the watermark is completely outside the base image, move it to the edge
    start_y = max(0, y)
    start_x = max(0, x)
    end_y = min(h_b, y + h_w)
    end_x = min(w_b, x + w_w)

    # calculate corresponding coordinates on the watermark image
    watermark_start_y = start_y - y
    watermark_start_x = start_x - x
    watermark_end_y = watermark_start_y + (end_y - start_y)
    watermark_end_x = watermark_start_x + (end_x - start_x)

    # cut out the region of interest from the base image and the corresponding part of the watermark
    roi = base_img[start_y:end_y, start_x:end_x]
    watermark_crop = watermark_img[watermark_start_y:watermark_end_y, watermark_start_x:watermark_end_x]

    # get if watermark has alpha channel (transparency, 4 paramters)
    if watermark_img.shape[2] == 4:
        # get alpha channel and normalize it to range [0, 1], the alha is 2d array with values from 0 to 255, we need to divide it by 255 to get values from 0 to 1
        alpha = watermark_crop[:, :, 3] / 255.0
        alpha = np.expand_dims(alpha, axis=2)  # what the hell is this
        # alright this is becouse the color stuff was lost when we got alpha channel, so we need to expand it to 3 channels to do the blending, now alpha is 
        # 3d array with same width and height as watermark_crop but with 3 channels where all channels have same value from original alpha channel

        roi_rgb = roi[:, :, :3] # get only the color channels from roi (in case it has alpha, we ignore it)
        watermark_rgb = watermark_crop[:, :, :3]

        # blend the watermark with the roi using the alpha channel, the formula is: blended = (watermark * alpha) + (roi * (1 - alpha)), this will give us the final color of each pixel after applying the watermark
        blended = (watermark_rgb * alpha) + (roi_rgb * (1.0 - alpha))

        # assign the blended result back to the base image, we need to convert it to uint8 because the blending will give us float values, and we need to convert it back to 0-255 range for the image
        base_img[start_y:end_y, start_x:end_x] = blended.astype(np.uint8)
    else:
        # if logo has no alpha channel, we just overlay it directly (this will completely cover the base image in that area)
        base_img[start_y:end_y, start_x:end_x] = watermark_crop[:, :, :3]

    return base_img

"""
    Function for reading config bullshit for reading cropping things
    param: config - read config (hashmap)
    return: will_be_cropped_width - boolean if cropping will be done on width
    return: will_be_cropped_height - boolean if cropping will be done on height
    return: x - from where cropping will be done on width
    return: cx - to where cropping will be done on width
    return: y - from where cropping will be done on height
    return: cy - to where cropping will be done on height
"""
def decide_to_crop_image(config):
    will_be_cropped_width = True
    x = NOT_FOUND_PARAMETER
    cx = NOT_FOUND_PARAMETER
    try: # check for x, cx parameters
        x = int(config['x'])
        cx = int(config['cx'])
    except KeyError as e:
        print("Invalid or missing x/cx in config, images will not be cropped on width")
        will_be_cropped_width = False

    will_be_cropped_height = True
    y = NOT_FOUND_PARAMETER
    cy = NOT_FOUND_PARAMETER
    try:  # check for x, cx parameters
        y = int(config['y'])
        cy = int(config['cy'])
    except KeyError as e:
        print("Invalid or missing y/cy in config, images will not be cropped on height")
        will_be_cropped_height = False

    if will_be_cropped_width:
        print("Images will be cropped on width. x: " + str(x) + ", cx: " + str(cx))

    if will_be_cropped_height:
        print("Images will be cropped on height. y: " + str(y) + ", cy: " + str(cy))

    return will_be_cropped_width, will_be_cropped_height, x, cx, y, cy


"""
    Function to crop an image horizontally based on given coordinates and dimensions, ensuring that the cropping area does not
    exceed the image boundaries.
    param: image - the image to crop (as a numpy array)
    param: x - top-left x coordinate of the cropping area
    param: cx - width of the cropping area
"""
def crop_image_width(image, x, cx):
    # if no image was loaded, return None
    if image is None:
        return None

    # get maximum dimensions of the image
    height, width = image.shape[:2]

    # check if x + cx is greater than the image width, if so, adjust cx to fit within the image
    start_x = max(0, x)
    end_x = min(width, x + cx)

    # crop the image using the calculated coordinates, if the coordinates are valid, otherwise return None
    cropped_img = image[:, start_x:end_x]

    return cropped_img


"""
    Function to crop an image vertically based on given coordinates and dimensions, ensuring that the cropping area does not
    exceed the image boundaries.
    param: image - the image to crop (as a numpy array)
    param: y - top-left y coordinate of the cropping area
    param: cy - height of the cropping area
"""
def crop_image_height(image, y, cy):
    # if no image was loaded, return None
    if image is None:
        return None

    # get maximum dimensions of the image
    height, width = image.shape[:2]

    # check if y + cy is greater than the image height, if so, adjust cy to fit within the image
    start_y = max(0, y)
    end_y = min(height, y + cy)

    # crop the image using the calculated coordinates, if the coordinates are valid, otherwise return None
    cropped_img = image[start_y:end_y, :]

    return cropped_img

"""
    Function to clean up old images from the specified directory based on the configuration.
    param: config - dictionary of parameters, expected keys:
        - wantDirectoryClean (str): "true" if cleanup is enabled, otherwise "false"
        - folder (str): Directory to clean
        - prefix (str): Prefix of image files to consider for deletion
        - hours (float): Age in hours; files older than this will be deleted
"""
def clean_directory(config):
    if str(config.get('want_directory_clean', 'false')).lower() != 'true': # control if cleanup is enabled
        print("Directory cleanup is disabled in config. Skipping cleanup.")
        return

    print("--- Starting Directory Cleanup ---")
    try: # check for mandatory parameters
        image_folder = config['folder']
        hours_back = float(config['hours'])
        file_prefix = config['prefix']
    except KeyError as e:
        print(f"Cleanup Error: Missing parameter {e}")
        return

    # calculate the timestamp threshold for deletion
    time_threshold = datetime.datetime.now() - datetime.timedelta(hours=hours_back)
    threshold_timestamp = time_threshold.timestamp()
    deleted_count = 0

    if not os.path.exists(image_folder):
        return

    for filename in os.listdir(image_folder): # go over all files in directory if older and have prefix, delete them
        if filename.startswith(file_prefix) and filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            file_path = os.path.join(image_folder, filename)
            if os.path.getmtime(file_path) < threshold_timestamp:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except OSError as e:
                    print(f"Warning: Failed to delete {file_path}: {e}")

    print(f"Cleanup finished. Deleted {deleted_count} old images.")

"""
    Loads configuration from a file. Expects key=value format.
    Returns a dictionary of parameters.
    param: config_path - path to config file
    return: dictionary of parameters (e.g., {'folder': 'path/to/images', 'prefix': 'img_', ...})
"""
def load_config(config_path):

    params = {}
    if not os.path.exists(config_path): # no config file
        print(f"Error: Configuration file '{config_path}' does not exist.")
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines or comments
            if not line or line.startswith('#'):
                continue

            if '=' in line:
                key, value = line.split('=', 1)
                params[key.strip().lower()] = value.strip()

    return params

"""
    Helper function to safely read an image (handling paths with special/non-ASCII characters).
    param: file_path - path to the image file
    return: image as a numpy array (or None if error)
"""
def read_image_safe(file_path):
    try:
        with open(file_path, "rb") as f:
            file_bytes = bytearray(f.read())
            numpy_array = np.asarray(file_bytes, dtype=np.uint8)
            return cv2.imdecode(numpy_array, cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"Error reading file stream: {e}")
        return None
    
""""
    Function to generate output filename based on config. If the filename ends with <h>, it will be replaced with a timestamp.
    param: output_filename - the original output filename from config
    return: the final output filename to use for the video
"""
def get_output_filename(output_filename):
    name, ext = os.path.splitext(output_filename)
    
    # check if name ends with <h> to decide if we need to generate dynamic filename with timestamp
    if name.endswith('<h>'):
        # get current timestamp in format YYYY.MM.DD.HH.MM.SS
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        
        # remove the <h> from the name and append the timestamp
        new_name = name[:-3] + "_" + timestamp
        
        # reconstruct the output filename with the new name and original extension
        output_filename = new_name + ext
        
        print(f"Output filename dynamically set to: {output_filename}")
        return output_filename
    else:
        return output_filename

"""
    Function to create a timelapse video based on the provided configuration.
    param: config - dictionary of parameters loaded from config file, expected keys:
        - folder (str): Directory containing the images
        - prefix (str): Prefix of image files to include
        - hours (float): Time range in hours to include images from
        - duration (float): Duration of each frame in milliseconds
        - output (str): Output video filename (e.g., "timelapse.mp4")
        - width (int, optional): Target width of video frames (if not specified, uses original image width)
        - height (int, optional): Target height of video frames (if not specified, uses original image height)
"""
def create_timelapse(config):
    try:
        image_folder = config['folder']
        file_prefix = config['prefix']
        hours_back = float(config['hours'])
        frame_duration = float(config['duration'])
        output_filename = get_output_filename(config['output'])
    except KeyError as e:
        print(f"Error: Missing parameter: {e}")
        return

    target_width = int(config.get('width')) if config.get('width') else None
    target_height = int(config.get('height')) if config.get('height') else None

    # get all files with prefix and within time range (in memory only string, not images)
    time_threshold = datetime.datetime.now() - datetime.timedelta(hours=hours_back)

    print(f"Scanning {image_folder}...")
    all_files = []
    for filename in os.listdir(image_folder):
        if filename.startswith(file_prefix) and filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            path = os.path.join(image_folder, filename)
            mtime = os.path.getmtime(path)
            if datetime.datetime.fromtimestamp(mtime) >= time_threshold:
                all_files.append((path, mtime))

    if not all_files:
        print("No images found.")
        return

    # sort by modification time (oldest first)
    all_files.sort(key=lambda x: x[1])

    video_writer = None
    fps = 1000.0 / frame_duration
    count = 0

    crop_width, crop_height, x, cx, y, cy = decide_to_crop_image(config)
    watermarks_from_config = get_watermarks(config)

    # main loop - read, resize, write (only one image in memory at a time)
    for file_path, _ in all_files:
        img = read_image_safe(file_path) # safe reading to handle special characters in paths
        if img is None:
            continue

        # Initialize video writer on the first image (after we know dimensions), or use target dimensions if specified
        if video_writer is None:
            h, w, _ = img.shape # get first images dimensions
            target_width = target_width or w # give to target width what was in config or what was in first image
            target_height = target_height or h # give to target height what was in config or what was in first image
            fourcc = cv2.VideoWriter_fourcc(*'mp4v') # use mp4v codec for .mp4 output
            video_writer = cv2.VideoWriter(output_filename, fourcc, fps, (target_width, target_height))
            print(f"Video started: {target_width}x{target_height} @ {fps} FPS")

        # crop image if wanted
        if crop_width:
            img = crop_image_width(img, x, cx)

        if crop_height:
            img = crop_image_height(img, y, cy)

        # apply watermarks if any
        if watermarks_from_config:
            img = apply_all_watermarks(img, watermarks_from_config)

        # resize image if target dimensions are specified, otherwise keep original size
        img_resized = cv2.resize(img, (target_width, target_height))
        video_writer.write(img_resized)

        count += 1
        if count % 10 == 0: # print progress every 10 frames
            print(f"Processing frame {count}/{len(all_files)}...", end='\r')

    if video_writer:
        video_writer.release()
        print(f"\nDone! Processed {count} images.")
    else:
        print("\nNo video was created.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a timelapse video from a config file.")
    parser.add_argument("config_file", help="Path to the configuration file (e.g., config.txt)")
    args = parser.parse_args()
    config_data = load_config(args.config_file)

    ftp.download_new_from_ftp(config_data)
    create_timelapse(config_data)

    ftp.upload_video_to_ftp(config_data)

    clean_directory(config_data)