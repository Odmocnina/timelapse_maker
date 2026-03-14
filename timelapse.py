import cv2
import os
import argparse
import datetime
import numpy as np
import sys
import ffmpeg_handeler as ffmpeg
import ftp_handeler as ftp
from PIL import Image
import io
import logging

NOT_FOUND_PARAMETER = -1
logger = None

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
        logger.warning(f"Could not load watermark image '{path}': {e}")
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
                    logger.info(f"Found watermark '{key}': {logo_path}, Position: x={logo_x}, y={logo_y}")
                except ValueError: # if something is fucked up with coordinates, skip this logo item
                    logger.warning(f"Warning: Invalid coordinates in '{key}' ('{value}'). Skipping this watermark.")
            else:
                logger.warning(f"Warning: Invalid format for '{key}' ('{value}'). Expected 'path;x;y'. Skipping.")
                
    return watermarks

"""
    Function to get absolute path from a given path string. If the path is already absolute, it will be returned as is. If it's a relative path, it will
    be joined with the directory of the currently running script to form an absolute path.
    param: path_str - the input path string (can be absolute or relative)
    return: absolute path string
"""
def get_absolute_path(path_str):
    if not path_str:
        return path_str
        
    # get the directory of the currently running script, this will be used to resolve relative paths correctly regardless of the current working directory when the script is run
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # check if the path is already absolute (starts with / or is an absolute path on Windows), if so, return it as is
    if os.path.isabs(path_str) or path_str.startswith('/'):
        return os.path.abspath(path_str)
    else:
        # if the path is relative, join it with the script directory to get the absolute path, this ensures that all paths are resolved relative to the script location, which is important for consistent behavior when the script is run from different directories
        joined_path = os.path.join(script_dir, path_str)
        return os.path.abspath(joined_path)

"""
    Function to get the time range for processing based on 'days' or 'hours' parameter in config.
    Supports 'T' (Today) and 'Y' (Yesterday) for days. If days is a number, it will be treated as days back.
    param: config - dictionary of parameters, expected key:
        - days (str): number of days back (e.g., "2") or "T" for today or "Y" for yesterday
        - hours (int): number of hours back (e.g., 24)
    return: tuple of (start_time, end_time) in datetime objects
"""
def get_time_range(config):
    now = datetime.datetime.now()
    
    if 'days' in config:
        days_val = str(config['days']).strip().upper()
        
        if days_val == 'T':
            # today from 0 to 24
            midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return midnight_today, now
            
        elif days_val == 'Y':
            # yesterday from 0 to 24
            midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            midnight_yesterday = midnight_today - datetime.timedelta(days=1)
            return midnight_yesterday, midnight_today
            
        else:
            # number of days back to now
            try:
                start_time = now - datetime.timedelta(days=float(days_val))
                return start_time, now
            except ValueError:
                if logger:
                    logger.warning(f"Invalid 'days' value: {days_val}. Trying to use 'hours'.")
    
    # if days is not in config or is invalid, try hours
    if 'hours' in config:
        start_time = now - datetime.timedelta(hours=float(config['hours']))
        return start_time, now
        
    raise KeyError("Missing 'hours' or 'days' parameter in config")
    
"""
    Function to normalize paths in the configuration dictionary. It checks specific keys that are expected to contain paths (e.g., 'folder', 'video_folder', 'log_dir') and converts their values to absolute paths using the get_absolute_path function. This ensures that all path-related parameters in the config are in a consistent absolute format, which helps avoid issues with relative paths when the script is run from different locations.
    param: config - dictionary of parameters loaded from config file
    return: config with normalized absolute paths for specified keys
"""
def normalize_config_paths(config):
    # path keys that we want to normalize, you can add more keys here if your config has other path parameters that need to be normalized
    path_keys = ['folder', 'video_folder', 'log_dir', 'ffmpeg_win_pathname', 'ffmpeg_pathname']
    
    for key, value in config.items():
        # normalize paths for specific keys that are expected to contain paths, this will convert relative paths to absolute paths based on the script location, ensuring consistent behavior regardless of the current working directory when the script is run
        if key in path_keys:
            config[key] = get_absolute_path(value)
            
        # normalize paths for logo items, since they can also contain paths that need to be resolved, we check if the key starts with 'logo' and then we split the value by ';' to get the path part, normalize it, and then join it back together, this allows us to handle multiple logo items in the config that may have different paths that need to be normalized
        elif key.startswith('logo'):
            parts = value.split(';')
            if len(parts) > 0:
                # take the first part of the logo value, which is expected to be the path, and normalize it, this ensures that all logo paths are also converted to absolute paths, which is important for correctly loading the watermark images regardless of where the script is run from
                normalized_logo_path = get_absolute_path(parts[0].strip())
                # replace the original path with the normalized one
                parts[0] = normalized_logo_path
                # join the parts back into a string (path;x;y) and save it back to the config
                config[key] = ';'.join(parts)

        elif key.startswith("glob_config"):
            config[key] = get_absolute_path(value)

            
    return config

"""
    Function for setting up the outfile, if the video_name in config ends with <h>, it will be replaced with a timestamp, otherwise it will be used as is.
    param: config - dictionary of parameters, expected key:
        - video_name (str): output video filename (e.g., "timelapse.mp4" or "timelapse_<h>.mp4")
        - video_folder (str, optional): Directory to save the video, if not specified, video will be saved in current directory
    return: config with updated 'video_name' key containing the final video filename
"""
def set_up_outfile(config):
    video_folder = None
    try:
        video_folder = config['video_folder']
    except KeyError as e:
        logger.warning(f"Video folder not set in config. Video will be saved to photo directory. Missing parameter: {e}")

    if video_folder is not None:
        if not os.path.exists(video_folder):
            try:
                os.makedirs(video_folder)
                logger.info(f"Created video output directory: {video_folder}")
            except OSError as e:
                logger.warning(f"Could not create video output directory '{video_folder}': {e}. Video will be saved in current directory.")
                video_folder = None

    if video_folder is None:
        logger.info("No video output directory specified or could not be created. Video will be saved to photo directory.")
        config["video_folder"] = config["folder"] # if no video folder is specified, use the photo folder for output
        video_folder = config["folder"]
    
    config['video_name'] = os.path.join(video_folder, get_video_name_filename(config['video_name']))

    return config

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
    Function to remove old videos from the specified directory based on the configuration. Videos that start with the specified prefix and are older than the specified number of hours will be deleted.
    param: config - dictionary of parameters, expected keys:
        - want_video_clean (str): "true" if video cleanup is enabled, otherwise "false"
        - video_folder (str): Directory where videos are stored
        - video_prefix (str): Prefix of video files to consider for deletion
        - directory_clean_mp4_hours (float): Age in hours; video files older than this will be deleted
"""
def clear_video_dir(config):
    if str(config.get('want_video_clean', 'false')).lower() != 'true':
        logger.info("Video cleanup is disabled in config. Skipping cleanup.")
        return

    logger.info("--- Starting Video Cleanup ---")
    try:
        video_folder = config['video_folder']
        hours_back = float(config['directory_clean_mp4_hours'])
    except KeyError as e:
        logger.warning(f"Cleanup Error: Missing parameter {e}")
        return

    time_threshold = datetime.datetime.now() - datetime.timedelta(hours=hours_back)
    threshold_timestamp = time_threshold.timestamp()
    deleted_count = 0

    if not os.path.exists(video_folder):
        return

    for filename in os.listdir(video_folder):
        if filename.lower().endswith(('.mp4')):
            file_path = os.path.join(video_folder, filename)
            if os.path.getmtime(file_path) < threshold_timestamp:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except OSError as e:
                    logger.warning(f"Warning: Failed to delete {file_path}: {e}")

    logger.info(f"Video cleanup finished. Deleted {deleted_count} old videos.")

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
        x = config['x']
        cx = config['cx']
    except KeyError as e:
        logger.info("Missing x/cx in config, images will not be cropped on width")
        will_be_cropped_width = False

    will_be_cropped_height = True
    y = NOT_FOUND_PARAMETER
    cy = NOT_FOUND_PARAMETER
    try:  # check for x, cx parameters
        y = config['y']
        cy = config['cy']
    except KeyError as e:
        logger.info("Missing y/cy in config, images will not be cropped on height")
        will_be_cropped_height = False

    if will_be_cropped_width:
        try:
            x = int(x)
            cx = int(cx)

            if x < 0 or cx <= 0:
                logger.warning(f"Invalid x/cx values in config (x: {x}, cx: {cx}), needs to be positive integer, images will not be cropped on width")
                will_be_cropped_width = False
        except ValueError:
            logger.warning(f"Invalid x/cx values in config (x: {x}, cx: {cx}), needs to be integer, images will not be cropped on width")
            will_be_cropped_width = False

    if will_be_cropped_height:
        try:
            y = int(y)
            cy = int(cy)

            if y < 0 or cy <= 0:
                logger.warning(f"Invalid y/cy values in config (y: {y}, cy: {cy}), needs to be positive integer, images will not be cropped on height")
                will_be_cropped_height = False
        except ValueError:
            logger.warning(f"Invalid y/cy values in config (y: {y}, cy: {cy}), needs to be integer, images will not be cropped on height")
            will_be_cropped_height = False

    if will_be_cropped_width:
        logger.info("Images will be cropped on width. x: " + str(x) + ", cx: " + str(cx))

    if will_be_cropped_height:
        logger.info("Images will be cropped on height. y: " + str(y) + ", cy: " + str(cy))

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
        - want_image_clean (str): "true" if cleanup is enabled, otherwise "false"
        - folder (str): Directory to clean
        - prefix (str): Prefix of image files to consider for deletion
        - image_clean_hours (float): Age in hours; files older than this will be deleted
"""
def clean_directory(config):
    if str(config.get('want_image_clean', 'false')).lower() != 'true': # control if cleanup is enabled
        logger.info("Directory cleanup is disabled in config. Skipping cleanup.")
        return

    logger.info("--- Starting Directory Cleanup ---")
    try: # check for mandatory parameters
        image_folder = config['folder']
        hours_back = float(config['image_clean_hours'])
        file_prefix = config['prefix']
    except KeyError as e:
        logger.warning(f"Cleanup Error: Missing parameter {e}")
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
                    logger.warning(f"Warning: Failed to delete {file_path}: {e}")

    logger.info(f"Cleanup finished. Deleted {deleted_count} old images.")

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
            print("Line: ", line)
            line = line.strip()
            # Skip empty lines or comments
            if not line or line.startswith('#'):
                continue

            if '=' in line:
                key, value = line.split(':=', 1)
                params[key.strip().lower()] = value.strip()

    # if os is windows, use the windows ffmpeg path
    if os.name == 'nt':
        try:
            params['ffmpeg_pathname'] = params['ffmpeg_win_pathname']
        except KeyError:
            pass

    print("Loaded config: ", config_path)
    return params

"""
    Function to print configuration to log.
    param: config - dictionary of parameters
"""
def print_config(config):
    for key, value in config.items():
        if key != "ftp_password":
            logger.debug(f"Parameter '{key}': {value}")

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
        logger.warning(f"Error reading file stream: {e}")
        return None
    
""""
    Function to generate video filename based on config. If the filename ends with <h>, it will be replaced with a timestamp.
    param: video_name_filename - the original video filename from config
    return: the final video_name filename to use for the video
"""
def get_video_name_filename(video_name_filename):
    name, ext = os.path.splitext(video_name_filename)
    
    # check if name ends with <h> to decide if we need to generate dynamic filename with timestamp
    if name.endswith('<h>'):
        # get current timestamp in format YYYY.MM.DD.HH.MM.SS
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        
        # remove the <h> from the name and append the timestamp
        new_name = name[:-3] + "_" + timestamp
        
        # reconstruct the video_name filename with the new name and original extension
        video_name_filename = new_name + ext
        
        logger.info(f"Video filename dynamically set to: {video_name_filename}")
        return video_name_filename
    else:
        logger.info(f"Video filename set to: {video_name_filename}")
        return video_name_filename

"""
    Function to create a timelapse video based on the provided configuration.
    param: config - dictionary of parameters loaded from config file, expected keys:
        - folder (str): Directory containing the images
        - prefix (str): Prefix of image files to include
        - hours (float): Time range in hours to include images from
        - duration (float): Duration of each frame in milliseconds
        - video_name (str): filename of output video (e.g., "timelapse.mp4")
        - width (int, optional): Target width of video frames (if not specified, uses original image width)
        - height (int, optional): Target height of video frames (if not specified, uses original image height)
"""
def create_timelapse(config):
    try:
        image_folder = config['folder']
        file_prefix = config['prefix']
        start_time, end_time = get_time_range(config) # get start and end time
        frame_duration = float(config['duration'])
        video_name_filename = get_video_name_filename(config['video_name'])
    except KeyError as e:
        logger.error(f"Error: Missing mandatory parameter: {e}")
        return

    target_width = int(config.get('width')) if config.get('width') else None
    target_height = int(config.get('height')) if config.get('height') else None

    logger.info(f"Scanning {image_folder} for images with prefix '{file_prefix}' from {start_time} to {end_time}.")
    all_files = []
    
    for filename in os.listdir(image_folder):
        if filename.startswith(file_prefix) and filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            path = os.path.join(image_folder, filename)
            mtime = os.path.getmtime(path)
            file_dt = datetime.datetime.fromtimestamp(mtime)
            
            # check if image is within the time range (from start_time to end_time)
            if start_time <= file_dt <= end_time:
                all_files.append((path, mtime))

    if not all_files:
        logger.warning("No images found for the specified time range. No video will be created.")
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
            fourcc = cv2.VideoWriter_fourcc(*'mp4v') # use mp4v codec for .mp4 video
            video_writer = cv2.VideoWriter(video_name_filename, fourcc, fps, (target_width, target_height))
            logger.info(f"Video started: {target_width}x{target_height} @ {fps} FPS")

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
            logger.debug(f"Processed {count} frames so far.")

    if video_writer:
        video_writer.release()
        logger.info(f"Timelapse video created: {video_name_filename} with {count} frames.")
    else:
        logger.warning("No video was created because no valid images were found.")

"""
    Function to set up logging based on configuration. If 'log_to_file' is set to true in config, logs will be written to 'app.log' with UTF-8 encoding.
    Logs will also be printed to console and file if wanted. The log format includes timestamp, log level, and message.
    param: config - dictionary of parameters, expected key:
        - log_to_file (str): "true" to enable logging to file, otherwise "false"
    return: configured logger instance
"""
def set_up_logging(config, config_file_name):
    # create logger
    logger = logging.getLogger("logger")
    logger.setLevel(logging.DEBUG)  # catch all levels of logs (DEBUG and above)

    # create formatter with timestamp, log level and message, the date format is set to be more readable
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', 
                                datefmt='[%Y-%m-%d %H:%M:%S]')

    if str(config.get('log_to_file', 'false')).lower() == 'true':
        # make file handler for logging to a file, set encoding to utf-8 to handle special characters in log messages, and set the formatter
        log_file = "app.log"  # default log file name
        try:
            if config["log_file"]: # if log file is specified in config, use it, otherwise use default 'app.log'
                log_file = config["log_file"]
        except KeyError:
            logger.info("Log file not specified in config, will try to use default 'app.log' or log file with timestamp if log_dir is specified.")
        
        if log_file == "app.log": # if default log file is used, check if log_dir is specified in config, if so, create a log file with timestamp in that directory
            try:
                if config["log_dir"]:
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
                    log_file = os.path.join(config["log_dir"], f"{os.path.splitext(os.path.basename(config_file_name))[0]}_{timestamp}.log")
            except KeyError:
                logger.info("Log directory not specified in config, will use default log file name or log file specified in config if it exists.")  

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)

        logger.addHandler(file_handler)

    # make console handler for logging to console, and set the same formatter so logs look the same in file and console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)

    return logger

"""
    Funtion that gets log file name like logs/config2_2026-02-21-21-58-46.log and returns the timestamp part as datetime object, in this case 2026-02-21 21:58:46
    param: log_file - the path to the log file
    return: datetime object representing the timestamp extracted from the log file name, or None if it cannot be extracted
"""
def get_time_of_log_file(log_file):
    try:
        base_name = os.path.basename(log_file) # get just the file name without directories
        name_part = os.path.splitext(base_name)[0] # remove the extension to get the name part
        timestamp_str = name_part.split('_')[-1] # get the last part after underscore, which should be the timestamp
        return datetime.datetime.strptime(timestamp_str, "%Y-%m-%d-%H-%M-%S") # parse the timestamp string into a datetime object
    except Exception as e:
        logger.warning(f"Could not extract timestamp from log file name '{log_file}': {e}")
        return None

"""
    Function that handles global configs by loading them and updating the main config with them.
    param: config - dictionary of parameters, expected keys:
        - global_config (str): Path to the global config file
    param: original_config_path - path to the original config file
    return: updated config dictionary
"""
def handle_global_configs(config, original_config_path):
    for key, value in list(config.items()):
        if 'glob_config' in key:
            print(f"Loading global config: {value}")
            global_config = load_config(value)
            config.update(global_config)

    original_config = load_config(original_config_path)
    config.update(original_config)
    
    return config

"""
    Function for cleaning up old logs from the specified log directory based on the configuration.
    param: config - dictionary of parameters, expected keys:
        - clear_log_dir (str): "true" if log cleanup is enabled, otherwise "false"
        - log_dir (str): Directory where log files are stored
        - log_clean_days (int): Age in days; log files older than this will be deleted
"""
def clear_log_dir(config):
    if str(config.get('clear_log_dir', 'false')).lower() != 'true':
        logger.info("Log directory cleanup not enabled in config.")
        return
    
    logger.info("--- Starting Log Directory Cleanup ---")

    log_dir = config.get('log_dir')
    if not log_dir:
        logger.warning("Log directory not specified in config, cannot perform cleanup.")
        return

    if not os.path.exists(log_dir):
        logger.info(f"Log directory '{log_dir}' does not exist, no logs to clean.")
        return
    
    try:
        days_back = int(config.get('log_clean_days', NOT_FOUND_PARAMETER))
    except ValueError:
        logger.warning(f"Invalid log clean days specified in config ({config.get('log_clean_days', NOT_FOUND_PARAMETER)}), cannot perform cleanup.")
        return
    
    if days_back == NOT_FOUND_PARAMETER:
        logger.warning("Log clean days not specified in config, cannot perform cleanup.")
        return
    
    if days_back < 0:
        logger.warning(f"Log clean days cannot be negative ({days_back}), cannot perform cleanup.")
        return
    
    time_threshold = datetime.datetime.now() - datetime.timedelta(days=days_back)

    deleted_count = 0
    for filename in os.listdir(log_dir):
        file_path = os.path.join(log_dir, filename)
        try:
            if os.path.isfile(file_path):
                file_time_from_name = get_time_of_log_file(file_path)
                if file_time_from_name < time_threshold:
                    os.remove(file_path)
                    deleted_count += 1
                    logger.info(f"Deleted log file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to delete log file '{file_path}': {e}")

    logger.info(f"Log directory cleanup finished. Deleted {deleted_count} log files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a timelapse video from a config file.")
    parser.add_argument("config_file", help="Path to the configuration file (e.g., config.txt)")
    args = parser.parse_args()
    config_data = load_config(args.config_file)
    config_data = normalize_config_paths(config_data)

    # handle global configs
    config_data = handle_global_configs(config_data, args.config_file)
    config_data = normalize_config_paths(config_data)

    logger = set_up_logging(config_data, args.config_file)
    config_data = set_up_outfile(config_data)
    print_config(config_data)

    # download new stuff (if enebled in config) and create vid
    ftp.download_new_from_ftp(config_data, logger)
    create_timelapse(config_data)

    # process the created video with FFmpeg if enabled in config
    ffmpeg.compress_video_with_ffmpeg(config_data, logger)

    # upload video to FTP if enabled in config
    ftp.upload_video_to_ftp(config_data, logger)

    # clean image and log directories if enabled in config
    clean_directory(config_data)
    clear_log_dir(config_data)
    clear_video_dir(config_data)