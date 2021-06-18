################################################################################
# Practical Libraries
################################################################################

# Logger library compatible with multiprocessing
from loguru import logger

# Library to get date and time for folder name and filename
import datetime

# Library to be able to sleep for a given duration
import time

# Libraries manipulate json format, execute bash commands
import json, shutil, os

# Library for starting processes
import multiprocessing

# Basic planktoscope libraries
import planktoscope.mqtt


################################################################################
# Morphocut Libraries
################################################################################
import morphocut
import morphocut.file
import morphocut.image
import morphocut.stat
import morphocut.stream
import morphocut.str
import morphocut.contrib.ecotaxa
import morphocut.contrib.zooprocess

################################################################################
# Other image processing Libraries
################################################################################
import skimage.util
import skimage.transform
import skimage.measure
import cv2
import scipy.stats
import numpy as np
import PIL.Image
import math


logger.info("planktoscope.segmenter is loaded")


################################################################################
# Main Segmenter class
################################################################################
class SegmenterProcess(multiprocessing.Process):
    """This class contains the main definitions for the segmenter of the PlanktoScope"""

    @logger.catch
    def __init__(self, event, data_path):
        """Initialize the Segmenter class

        Args:
            event (multiprocessing.Event): shutdown event
        """
        super(SegmenterProcess, self).__init__(name="segmenter")

        logger.info("planktoscope.segmenter is initialising")

        self.stop_event = event
        self.__pipe = None
        self.segmenter_client = None
        # Where captured images are saved
        self.__img_path = os.path.join(data_path, "img/")
        # To save export folders
        self.__export_path = os.path.join(data_path, "export/")
        # To save objects to export
        self.__objects_root = os.path.join(data_path, "objects/")
        # To save debug masks
        self.__debug_objects_root = os.path.join(data_path, "clean/")
        self.__ecotaxa_path = os.path.join(self.__export_path, "ecotaxa")
        self.__global_metadata = None
        # path for current folder being segmented
        self.__working_path = ""
        # combination of self.__objects_root and actual sample folder name
        self.__working_obj_path = ""
        # combination of self.__debug_objects_root and actual sample folder name
        self.__working_debug_path = ""
        self.__archive_fn = ""
        self.__flat = None
        self.__mask_array = None
        self.__mask_to_remove = None
        self.__save_debug_img = False

        # create all base path
        for path in [
            self.__ecotaxa_path,
            self.__objects_root,
            self.__debug_objects_root,
        ]:
            if not os.path.exists(path):
                # create the path!
                os.makedirs(path)

        logger.success("planktoscope.segmenter is initialised and ready to go!")

    def _find_files(self, path, extension):
        for _, _, filenames in os.walk(path, topdown=True):
            if filenames:
                filenames = sorted(filenames)
            return [fn for fn in filenames if fn.endswith(extension)]

    def _manual_median(self, array_of_5):
        array_of_5.sort(axis=0)
        return array_of_5[2]

    def _save_image(self, image, path):
        PIL.Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)).save(path)

    def _save_mask(self, mask, path):
        PIL.Image.fromarray(mask).save(path)

    def _calculate_flat(self, images_list, images_number, images_root_path):
        # TODO make this calculation optional if a flat already exists
        # make sure image number is smaller than image list
        if images_number > len(images_list):
            logger.error(
                "The image number can't be bigger than the lenght of the provided list!"
            )
            images_number = len(images_list)

        logger.debug("Opening images")
        # start = time.monotonic()
        # Read images and build array
        images_array = np.array(
            [
                cv2.imread(
                    os.path.join(images_root_path, images_list[i]),
                )
                for i in range(images_number)
            ]
        )

        # logger.debug(time.monotonic() - start)
        logger.success("Opening images")

        logger.info("Manual median calc")
        # start = time.monotonic()

        self.__flat = self._manual_median(images_array)
        # self.__flat = _numpy_median(images_array)

        # logger.debug(time.monotonic() - start)

        logger.success("Manual median calc")

        # cv2.imshow("flat_color", self.__flat.astype("uint8"))
        # cv2.waitKey(0)

        return self.__flat

    def _open_and_apply_flat(self, filepath, flat_ref):
        logger.info("Opening images")
        start = time.monotonic()
        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # Read images
        image = cv2.imread(filepath)
        # print(image)

        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # logger.debug(time.monotonic() - start)
        logger.success("Opening images")

        logger.info("Flat calc")
        # start = time.monotonic()
        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

        # Correct image
        image = image / self.__flat

        # adding one black pixel top left
        image[0][0] = [0, 0, 0]

        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # logger.debug(time.monotonic() - start)

        image = skimage.exposure.rescale_intensity(
            image, in_range=(0, 1.04), out_range="uint8"
        )
        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        logger.debug(time.monotonic() - start)
        logger.success("Flat calc")

        # cv2.imshow("img", img.astype("uint8"))
        # cv2.waitKey(0)
        if self.__save_debug_img:
            self._save_image(
                image,
                os.path.join(self.__working_debug_path, "cleaned_image.jpg"),
            )
        return image

    def _create_mask(self, img, saving_path):
        logger.info("Starting the mask creation")
        # start = time.monotonic()
        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

        logger.debug("Threshold calc")
        # img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # ret, img_thres = cv2.threshold(img_gray, 127, 200, cv2.THRESH_OTSU)
        img_thres = cv2.adaptiveThreshold(
            img_gray,
            maxValue=255,
            adaptiveMethod=cv2.ADAPTIVE_THRESH_MEAN_C,
            thresholdType=cv2.THRESH_BINARY_INV,
            blockSize=19,  # must be odd
            C=4,
        )
        # img_thres = 255 - img_thres

        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # logger.debug(time.monotonic() - start)
        # logger.success(f"Threshold used was {ret}")
        logger.success(f"Threshold is done")

        # cv2.imshow("img_thres", img_thres)
        # cv2.waitKey(0)
        if self.__save_debug_img:
            PIL.Image.fromarray(img_thres).save(
                os.path.join(saving_path, "mask_1_thres.jpg")
            )

        logger.info("Erode calc")
        # start = time.monotonic()
        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        img_erode = cv2.erode(img_thres, kernel)

        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # logger.debug(time.monotonic() - start)
        logger.success("Erode calc")

        # cv2.imshow("img_erode", img_erode.astype("uint8"))
        # cv2.waitKey(0)
        if self.__save_debug_img:
            PIL.Image.fromarray(img_erode).save(
                os.path.join(saving_path, "mask_2_erode.jpg")
            )

        logger.info("Dilate calc")
        # start = time.monotonic()
        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (4, 4))
        img_dilate = cv2.dilate(img_erode, kernel)

        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # logger.debug(time.monotonic() - start)
        logger.success("Dilate calc")

        # cv2.imshow("img_dilate", img_dilate.astype("uint8"))
        # cv2.waitKey(0)
        if self.__save_debug_img:
            PIL.Image.fromarray(img_dilate).save(
                os.path.join(saving_path, "mask_3_dilate.jpg")
            )

        logger.info("Close calc")
        # start = time.monotonic()
        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

        img_close = cv2.morphologyEx(img_dilate, cv2.MORPH_CLOSE, kernel)

        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # logger.debug(time.monotonic() - start)
        logger.success("Close calc")

        # cv2.imshow("img_close", img_close.astype("uint8"))
        # cv2.waitKey(0)
        if self.__save_debug_img:
            PIL.Image.fromarray(img_close).save(
                os.path.join(saving_path, "mask_4_close.jpg")
            )

        logger.info("Erode calc 2")
        # start = time.monotonic()
        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

        img_erode_2 = cv2.erode(img_close, kernel)

        # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # logger.debug(time.monotonic() - start)
        logger.success("Erode calc 2")

        # cv2.imshow("img_erode_2", img_erode_2.astype("uint8"))
        # cv2.waitKey(0)
        if self.__save_debug_img:
            self._save_mask(
                img_erode_2,
                os.path.join(saving_path, "mask_5_erode_2.jpg"),
            )

        img_final = self._apply_previous_mask(img_erode_2)
        if self.__save_debug_img:
            self._save_mask(
                img_final,
                os.path.join(saving_path, "mask_6_final.jpg"),
            )
        logger.success("Mask created")
        return img_final

    def _apply_previous_mask(self, mask):
        if self.__mask_to_remove is not None:
            # start = time.monotonic()
            # np.append(self.__mask_to_remove, img_erode_2)
            # logger.debug(time.monotonic() - start)
            mask_and = mask & self.__mask_to_remove
            img_final = mask - mask_and
            self.__mask_to_remove = mask
            logger.success("Done mask")
            return img_final
        else:
            logger.debug("First mask")
            self.__mask_to_remove = mask
            return mask

    def _get_color_info(self, bgr_img, mask):
        # bgr_mean, bgr_stddev = cv2.meanStdDev(bgr_img, mask=mask)
        # (b_channel, g_channel, r_channel) = cv2.split(bgr_img)
        quartiles = [0, 0.05, 0.25, 0.50, 0.75, 0.95, 1]
        # b_quartiles = np.quantile(b_channel, quartiles)
        # g_quartiles = np.quantile(g_channel, quartiles)
        # r_quartiles = np.quantile(r_channel, quartiles)
        hsv_img = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HSV)
        (h_channel, s_channel, v_channel) = cv2.split(hsv_img)
        # hsv_mean, hsv_stddev = cv2.meanStdDev(hsv_img, mask=mask)
        h_mean = np.mean(h_channel)  # add once numpy is upgraded to 1.20 , where=mask
        s_mean = np.mean(s_channel)
        v_mean = np.mean(v_channel)
        h_stddev = np.std(h_channel)
        s_stddev = np.std(s_channel)
        v_stddev = np.std(v_channel)
        # TODO Add skewness and kurtosis calculation (with scipy) here
        # using https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.skew.html#scipy.stats.skew
        # and https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.kurtosis.html#scipy.stats.kurtosis
        # h_quartiles = np.quantile(h_channel, quartiles)
        # s_quartiles = np.quantile(s_channel, quartiles)
        # v_quartiles = np.quantile(v_channel, quartiles)
        return {
            # "object_MeanRedLevel": bgr_mean[2][0],
            # "object_MeanGreenLevel": bgr_mean[1][0],
            # "object_MeanBlueLevel": bgr_mean[0][0],
            # "object_StdRedLevel": bgr_stddev[2][0],
            # "object_StdGreenLevel": bgr_stddev[1][0],
            # "object_StdBlueLevel": bgr_stddev[0][0],
            # "object_minRedLevel": r_quartiles[0],
            # "object_Q05RedLevel": r_quartiles[1],
            # "object_Q25RedLevel": r_quartiles[2],
            # "object_Q50RedLevel": r_quartiles[3],
            # "object_Q75RedLevel": r_quartiles[4],
            # "object_Q95RedLevel": r_quartiles[5],
            # "object_maxRedLevel": r_quartiles[6],
            # "object_minGreenLevel": g_quartiles[0],
            # "object_Q05GreenLevel": g_quartiles[1],
            # "object_Q25GreenLevel": g_quartiles[2],
            # "object_Q50GreenLevel": g_quartiles[3],
            # "object_Q75GreenLevel": g_quartiles[4],
            # "object_Q95GreenLevel": g_quartiles[5],
            # "object_maxGreenLevel": g_quartiles[6],
            # "object_minBlueLevel": b_quartiles[0],
            # "object_Q05BlueLevel": b_quartiles[1],
            # "object_Q25BlueLevel": b_quartiles[2],
            # "object_Q50BlueLevel": b_quartiles[3],
            # "object_Q75BlueLevel": b_quartiles[4],
            # "object_Q95BlueLevel": b_quartiles[5],
            # "object_maxBlueLevel": b_quartiles[6],
            "object_MeanHue": h_mean,
            "object_MeanSaturation": s_mean,
            "object_MeanValue": v_mean,
            "object_StdHue": h_stddev,
            "object_StdSaturation": s_stddev,
            "object_StdValue": v_stddev,
            # "object_minHue": h_quartiles[0],
            # "object_Q05Hue": h_quartiles[1],
            # "object_Q25Hue": h_quartiles[2],
            # "object_Q50Hue": h_quartiles[3],
            # "object_Q75Hue": h_quartiles[4],
            # "object_Q95Hue": h_quartiles[5],
            # "object_maxHue": h_quartiles[6],
            # "object_minSaturation": s_quartiles[0],
            # "object_Q05Saturation": s_quartiles[1],
            # "object_Q25Saturation": s_quartiles[2],
            # "object_Q50Saturation": s_quartiles[3],
            # "object_Q75Saturation": s_quartiles[4],
            # "object_Q95Saturation": s_quartiles[5],
            # "object_maxSaturation": s_quartiles[6],
            # "object_minValue": v_quartiles[0],
            # "object_Q05Value": v_quartiles[1],
            # "object_Q25Value": v_quartiles[2],
            # "object_Q50Value": v_quartiles[3],
            # "object_Q75Value": v_quartiles[4],
            # "object_Q95Value": v_quartiles[5],
            # "object_maxValue": v_quartiles[6],
        }

    def _extract_metadata_from_regionprop(self, prop):
        return {
            "label": prop.label,
            # width of the smallest rectangle enclosing the object
            "width": prop.bbox[3] - prop.bbox[1],
            # height of the smallest rectangle enclosing the object
            "height": prop.bbox[2] - prop.bbox[0],
            # X coordinates of the top left point of the smallest rectangle enclosing the object
            "bx": prop.bbox[1],
            # Y coordinates of the top left point of the smallest rectangle enclosing the object
            "by": prop.bbox[0],
            # circularity : (4∗π ∗Area)/Perim^2 a value of 1 indicates a perfect circle, a value approaching 0 indicates an increasingly elongated polygon
            "circ.": (4 * np.pi * prop.filled_area) / prop.perimeter ** 2,
            # Surface area of the object excluding holes, in square pixels (=Area*(1-(%area/100))
            "area_exc": prop.area,
            # Surface area of the object in square pixels
            "area": prop.filled_area,
            # Percentage of object’s surface area that is comprised of holes, defined as the background grey level
            "%area": 1 - (prop.area / prop.filled_area),
            # Primary axis of the best fitting ellipse for the object
            "major": prop.major_axis_length,
            # Secondary axis of the best fitting ellipse for the object
            "minor": prop.minor_axis_length,
            # Y position of the center of gravity of the object
            "y": prop.centroid[0],
            # X position of the center of gravity of the object
            "x": prop.centroid[1],
            # The area of the smallest polygon within which all points in the objet fit
            "convex_area": prop.convex_area,
            # # Minimum grey value within the object (0 = black)
            # "min": prop.min_intensity,
            # # Maximum grey value within the object (255 = white)
            # "max": prop.max_intensity,
            # # Average grey value within the object ; sum of the grey values of all pixels in the object divided by the number of pixels
            # "mean": prop.mean_intensity,
            # # Integrated density. The sum of the grey values of the pixels in the object (i.e. = Area*Mean)
            # "intden": prop.filled_area * prop.mean_intensity,
            # The length of the outside boundary of the object
            "perim.": prop.perimeter,
            # major/minor
            "elongation": np.divide(prop.major_axis_length, prop.minor_axis_length),
            # max-min
            # "range": prop.max_intensity - prop.min_intensity,
            # perim/area_exc
            "perimareaexc": prop.perimeter / prop.area,
            # perim/major
            "perimmajor": prop.perimeter / prop.major_axis_length,
            # (4 ∗ π ∗ Area_exc)/perim 2
            "circex": np.divide(4 * np.pi * prop.area, prop.perimeter ** 2),
            # Angle between the primary axis and a line parallel to the x-axis of the image
            "angle": prop.orientation / np.pi * 180 + 90,
            # # X coordinate of the top left point of the image
            # 'xstart': data_object['raw_img']['meta']['xstart'],
            # # Y coordinate of the top left point of the image
            # 'ystart': data_object['raw_img']['meta']['ystart'],
            # Maximum feret diameter, i.e. the longest distance between any two points along the object boundary
            # 'feret': data_object['raw_img']['meta']['feret'],
            # feret/area_exc
            # 'feretareaexc': data_object['raw_img']['meta']['feret'] / property.area,
            # perim/feret
            # 'perimferet': property.perimeter / data_object['raw_img']['meta']['feret'],
            "bounding_box_area": prop.bbox_area,
            "eccentricity": prop.eccentricity,
            "equivalent_diameter": prop.equivalent_diameter,
            "euler_number": prop.euler_number,
            "extent": prop.extent,
            "local_centroid_col": prop.local_centroid[1],
            "local_centroid_row": prop.local_centroid[0],
            "solidity": prop.solidity,
        }

    def _slice_image(self, img, name, mask, start_count=0):
        """Slice a given image using give mask

        Args:
            img (img array): Image to slice
            name (string): name of the original image
            mask (mask binary array): mask to use slice with
            start_count (int, optional): count start to number the objects, so each one is unique. Defaults to 0.

        Returns:
            tuple: (Number of saved objects, original number of objects before size filtering)
        """
        # TODO retrieve here all those from the global metadata
        minESD = 40  # microns
        minArea = math.pi * (minESD / 2) * (minESD / 2)
        pixel_size = 1.01  # to be retrieved from metadata
        # minsizepix = minArea / pixel_size / pixel_size
        minsizepix = (minESD / pixel_size) ** 2

        labels, nlabels = skimage.measure.label(mask, return_num=True)
        regionprops = skimage.measure.regionprops(labels)
        regionprops_filtered = [
            region for region in regionprops if region.bbox_area >= minsizepix
        ]
        object_number = len(regionprops_filtered)
        logger.debug(f"Found {nlabels} labels, or {object_number} after size filtering")

        # TODO Actually segment the images and save the ROI images (and their mask?) and the TSV for ecotaxa
        for (i, region) in enumerate(regionprops_filtered):
            region.label = i + start_count

            # Publish the object_id to via MQTT to Node-RED
            self.segmenter_client.client.publish(
                "status/segmenter/object_id",
                f'{{"object_id":"{region.label}"}}',
            )
            obj_image = img[region.slice]
            object_id = f"{name}_{i}"
            object_fn = os.path.join(self.__working_obj_path, f"{object_id}.jpg")
            self._save_image(obj_image, object_fn)

            if self.__save_debug_img:
                self._save_mask(
                    region.filled_image,
                    os.path.join(self.__working_debug_path, f"obj_{i}_mask.jpg"),
                )

            colors = self._get_color_info(obj_image, region.filled_image)
            metadata = self._extract_metadata_from_regionprop(region)
            self.__global_metadata["objects"].append(
                {
                    "name": f"{object_id}",
                    "metadata": {**metadata, **colors},
                }
            )

        if self.__save_debug_img:
            if object_number:
                for region in regionprops_filtered:
                    tagged_image = cv2.drawMarker(
                        img,
                        (int(region.centroid[1]), int(region.centroid[0])),
                        (0, 0, 255),
                        cv2.MARKER_CROSS,
                    )
                    tagged_image = cv2.rectangle(
                        img,
                        pt1=region.bbox[-3:-5:-1],
                        pt2=region.bbox[-1:-3:-1],
                        color=(150, 0, 200),
                        thickness=1,
                    )

                # contours = [region.bbox for region in regionprops_filtered]
                # for contour in contours:
                #    tagged_image = cv2.rectangle(
                #        img, pt1=(contours[0][1],contours[0][0]), pt2=(contours[0][3],contours[0][2]), color=(0, 0, 255), thickness=2
                #    )
                # contours = [region.coords for region in regionprops_filtered]
                # for contour in contours:
                #    tagged_image = cv2.drawContours(
                #        img_erode_2, contour, -1, color=(0, 0, 255), thickness=2
                #    )

                # cv2.imshow("tagged_image", tagged_image.astype("uint8"))
                # cv2.waitKey(0)
                self._save_image(
                    tagged_image,
                    os.path.join(self.__debug_objects_root, name, "tagged.jpg"),
                )
            else:
                self._save_image(
                    img,
                    os.path.join(self.__debug_objects_root, name, "tagged.jpg"),
                )
        return (object_number, len(regionprops))

    def _pipe(self):
        logger.info("Finding images")
        images_list = self._find_files(
            self.__working_path, ("JPG", "jpg", "JPEG", "jpeg")
        )
        logger.debug(f"Images found are {images_list}")
        images_count = len(images_list)
        logger.debug(f"We found {images_count} images, good luck!")

        first_start = time.monotonic()
        self.__mask_to_remove = None
        average = 0
        total_objects = 0
        average_objects = 0
        recalculate_flat = True
        # TODO check image list here to find if a flat exists
        # we recalculate the flat every 10 pictures
        if recalculate_flat:
            self._calculate_flat(images_list[i : i + 10], 10, self.__working_path)
            recalculate_flat = False

        if self.__save_debug_img:
            self._save_image(
                self.__flat,
                os.path.join(self.__working_debug_path, "flat_color.jpg"),
            )

        average_time = 0

        for (i, filename) in enumerate(images_list):
            name = os.path.splitext(filename)

            # we recalculate the flat if the heuristics detected we should
            if recalculate_flat:  # not i % 10 and i < (images_count - 10)
                if i > len(images_list) - 11:
                    flat = self._calculate_flat(
                        images_list[i - 10 : i], 10, self.__working_path
                    )
                else:
                    flat = self._calculate_flat(
                        images_list[i : i + 10], 10, self.__working_path
                    )
                recalculate_flat = False
                if self.__save_debug_img:
                    self._save_image(
                        self.__flat,
                        os.path.join(
                            os.path.dirname(self.__working_debug_path),
                            f"flat_color_{i}.jpg",
                        ),
                    )

            self.__working_debug_path = os.path.join(
                self.__debug_objects_root,
                self.__working_path.split(self.__img_path)[1].strip(),
                name,
            )

            logger.debug(f"The debug objects path is {self.__working_debug_path}")
            # Create the objects path
            if not os.path.exists(self.__working_debug_path):
                # create the path!
                os.makedirs(self.__working_debug_path)

            start = time.monotonic()
            logger.info(f"Starting work on {name}, image {i+1}/{images_count}")

            img = self._open_and_apply_flat(
                os.path.join(self.__working_path, images_list[i]), self.__flat
            )

            # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            # logger.debug(time.monotonic() - start)

            # start = time.monotonic()
            # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

            mask = self._create_mask(img, self.__working_debug_path)

            # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            # logger.debug(time.monotonic() - start)

            # start = time.monotonic()
            # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

            objects_count, _ = self._slice_image(img, name, mask, total_objects)
            total_objects += objects_count
            # Simple heuristic to detect a movement of the flow cell and a change in the resulting flat
            if objects_count > average_objects + 20:
                logger.debug(
                    f"We need to recalculate a flat since we have {objects_count} new objects instead of the average of {average_objects}"
                )
                recalculate_flat = True
            average_objects = (average_objects * i + objects_count) / (i + 1)

            # logger.debug(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            # logger.debug(time.monotonic() - start)
            delay = time.monotonic() - start
            average_time = (average_time * i + delay) / (i + 1)
            logger.success(
                f"Work on {name} is OVER! Done in {delay}s, average time is {average_time}s, average number of objects is {average_objects}"
            )
            logger.success(
                f"We also found {objects_count} objects in this image, at a rate of {objects_count / delay} objects per second"
            )
            logger.success(f"So far we found {total_objects} objects")

        total_duration = (time.monotonic() - first_start) / 60
        logger.success(
            f"{images_count} images done in {total_duration} minutes, or an average of {average_time}s per image or {total_duration*60/images_count}s per image"
        )
        logger.success(
            f"We also found {total_objects} objects, or an average of {total_objects / (total_duration * 60)}objects per second"
        )
        # cleanup
        # we're done free some mem
        self.__flat = None

    def segment_all(self, paths: list):
        """Starts the segmentation in all the folders given recursively

        Args:
            paths (list, optional): path list to recursively explore. Defaults to [self.__img_path].
        """
        img_paths = []
        for path in paths:
            for x in os.walk(path):
                if x[0] not in img_paths:
                    img_paths.append(x[0])
        self.segment_list(img_paths)

    def segment_list(self, path_list: list):
        """Starts the segmentation in the folders given

        Args:
            path_list (list): [description]
        """
        # TODO check for recursive flag and force flag here
        logger.info(f"The pipeline will be run in {len(path_list)} directories")
        logger.debug(f"Those are {path_list}")
        for path in path_list:
            logger.debug(f"{path}: Checking for the presence of metadata.json")
            if os.path.exists(os.path.join(path, "metadata.json")):
                # The file exists, let's run the pipe!
                if not self.segment_path(path):
                    logger.error(f"There was en error while segmenting {path}")
            else:
                logger.debug(f"Moving to the next folder, {path} has no metadata.json")
        # Publish the status "Done" to via MQTT to Node-RED
        self.segmenter_client.client.publish("status/segmenter", '{"status":"Done"}')

    def segment_path(self, path):
        """Starts the segmentation in the given path

        Args:
            path (string): path of folder to do segmentation in
        """
        logger.info(f"Loading the metadata file for {path}")
        with open(os.path.join(path, "metadata.json"), "r") as config_file:
            self.__global_metadata = json.load(config_file)
            logger.debug(f"Configuration loaded is {self.__global_metadata}")

        # Remove all the key,value pairs that don't start with acq, sample, object or process (for Ecotaxa)
        self.__global_metadata = dict(
            filter(
                lambda item: item[0].startswith(("acq", "sample", "object", "process")),
                self.__global_metadata.items(),
            )
        )

        project = self.__global_metadata["sample_project"].replace(" ", "_")
        date = datetime.datetime.utcnow().isoformat()
        sample = self.__global_metadata["sample_id"]

        # TODO Add process informations to metadata here

        # Define the name of the .zip file that will contain the images and the .tsv table for EcoTaxa
        self.__archive_fn = os.path.join(
            self.__ecotaxa_path,
            # filename includes project name, timestamp and sample id
            f"export_{project}_{date}_{sample}.zip",
        )

        self.__working_path = path

        # recreate the subfolder img architecture of this folder inside objects
        # when we split the working path with the base img path, we get the date/sample architecture back
        # os.path.relpath("/home/pi/data/img/2020-10-17/5/5","/home/pi/data/img/") => '2020-10-17/5/5'

        sample_path = os.path.relpath(self.__working_path, self.__img_path)

        logger.debug(f"base obj path is {self.__objects_root}")
        logger.debug(f"sample path is {sample_path}")

        self.__working_obj_path = os.path.join(self.__objects_root, sample_path)

        logger.debug(f"The working objects path is {self.__working_obj_path}")

        self.__working_debug_path = os.path.join(self.__debug_objects_root, sample_path)

        logger.debug(f"The debug objects path is {self.__working_debug_path}")

        # Create the paths
        for path in [self.__working_obj_path, self.__working_debug_path]:
            if not os.path.exists(path):
                # create the path!
                os.makedirs(path)

        logger.debug(f"The archive folder is {self.__archive_fn}")

        logger.info(f"Starting the pipeline in {path}")

        try:
            self._pipe()
        except Exception as e:
            logger.exception(f"There was an error in the pipeline {e}")
            return False

        # Add file 'done' to path to mark the folder as already segmented
        with open(os.path.join(self.__working_path, "done"), "w") as done_file:
            done_file.writelines(datetime.datetime.utcnow().isoformat())
        logger.info(f"Pipeline has been run for {path}")
        return True

    @logger.catch
    def treat_message(self):
        last_message = {}
        if self.segmenter_client.new_message_received():
            logger.info("We received a new message")
            last_message = self.segmenter_client.msg["payload"]
            logger.debug(last_message)
            self.segmenter_client.read_message()

        if "action" in last_message:
            # If the command is "segment"
            if last_message["action"] == "segment":
                path = None
                recursive = True
                force = False
                # {"action":"segment"}
                if "settings" in last_message:
                    if "force" in last_message["settings"]:
                        # force rework of already done folder
                        force = last_message["settings"]["force"]
                    if "recursive" in last_message["settings"]:
                        # parse folders recursively starting from the given parameter
                        recursive = last_message["settings"]["recursive"]
                    # TODO eventually add customisation to segmenter parameters here

                if "path" in last_message:
                    path = last_message["path"]

                # Publish the status "Started" to via MQTT to Node-RED
                self.segmenter_client.client.publish(
                    "status/segmenter", '{"status":"Started"}'
                )
                if path:
                    if recursive:
                        self.segment_all(path)
                    else:
                        self.segment_list(path)
                else:
                    self.segment_all(self.__img_path)

            elif last_message["action"] == "stop":
                logger.info("The segmentation has been interrupted.")

                # Publish the status "Interrupted" to via MQTT to Node-RED
                self.segmenter_client.client.publish(
                    "status/segmenter", '{"status":"Interrupted"}'
                )

            elif last_message["action"] == "update_config":
                logger.error(
                    "We can't update the configuration while we are segmenting."
                )

                # Publish the status "Interrupted" to via MQTT to Node-RED
                self.segmenter_client.client.publish(
                    "status/segmenter", '{"status":"Busy"}'
                )

            elif last_message["action"] != "":
                logger.warning(
                    f"We did not understand the received request {action} - {last_message}"
                )

    ################################################################################
    # While loop for capturing commands from Node-RED
    ################################################################################
    @logger.catch
    def run(self):
        """This is the function that needs to be started to create a thread"""
        logger.info(
            f"The segmenter control thread has been started in process {os.getpid()}"
        )

        # MQTT Service connection
        self.segmenter_client = planktoscope.mqtt.MQTT_Client(
            topic="segmenter/#", name="segmenter_client"
        )

        ################################################################################
        # Morphocut Libraries
        ################################################################################
        import morphocut
        import morphocut.file
        import morphocut.image
        import morphocut.stat
        import morphocut.stream
        import morphocut.str
        import morphocut.contrib.ecotaxa
        import morphocut.contrib.zooprocess

        ################################################################################
        # Other image processing Libraries
        ################################################################################
        import skimage.util
        import cv2

        # Instantiate the morphocut pipeline
        # self.__create_morphocut_pipeline()

        # Publish the status "Ready" to via MQTT to Node-RED
        self.segmenter_client.client.publish("status/segmenter", '{"status":"Ready"}')

        logger.success("Segmenter is READY!")

        # This is the loop
        while not self.stop_event.is_set():
            self.treat_message()
            time.sleep(0.5)

        logger.info("Shutting down the segmenter process")
        self.segmenter_client.client.publish("status/segmenter", '{"status":"Dead"}')
        self.segmenter_client.shutdown()
        logger.success("Segmenter process shut down! See you!")


# This is called if this script is launched directly
if __name__ == "__main__":
    # TODO This should be a test suite for this library
    segmenter_thread = SegmenterProcess(
        None, "/home/rbazile/Documents/pro/PlanktonPlanet/Planktonscope/Segmenter/data/"
    )
    segmenter_thread.segment_path(
        "/home/rbazile/Documents/pro/PlanktonPlanet/Planktonscope/Segmenter/data/test"
    )
