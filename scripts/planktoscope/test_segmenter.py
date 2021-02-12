#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Mar  3 09:17:46 2021

@author: robin
"""
import morphocut
import os
import json
import skimage
import cv2

with morphocut.Pipeline() as pipe:
            # TODO wrap morphocut.Call(logger.debug()) in something that allows it not to be added to the pipeline
            # if the logger.level is not debug. Might not be as easy as it sounds.
            # Recursively find .jpg files in import_path.
            # Sort to get consecutive frames.
            
            objects_base_path="/home/robin/Desktop/segmenter/objects"
            working_obj_path=os.path.join(objects_base_path, sample_path)
            working_path="/home/robin/Desktop/segmenter"
    
            abs_path = morphocut.file.Find(working_path, [".jpg"], sort=True, verbose=True)

            # Extract name from abs_path
            name = morphocut.Call(lambda p: os.path.splitext(os.path.basename(p))[0], abs_path)

            # Read image
            img = morphocut.image.ImageReader("/home/robin/Desktop/17_25_29_031485.jpg") #abs_path

            # Show progress bar for frames
            morphocut.stream.TQDM(morphocut.str.Format("Frame {name}", name=name))

            # Apply running median to approximate the background image
            flat_field = morphocut.stat.RunningMedian(img, 5)

            # Correct image
            img = img / flat_field

            # Rescale intensities and convert to uint8 to speed up calculations
            img = morphocut.image.RescaleIntensity(
                img, in_range=(0, 1.1), dtype="uint8"
            )

            # Filter variable to reduce memory load
            morphocut.stream.FilterVariables(name, img)

            # Save cleaned images
            # frame_fn = morphocut.str.Format(os.path.join("/home/pi/PlanktonScope/tmp","CLEAN", "{name}.jpg"), name=name)
            # morphocut.image.ImageWriter(frame_fn, img)

            # Convert image to uint8 gray
            img_gray = morphocut.image.RGB2Gray(img)

            # ?
            img_gray = morphocut.Call(skimage.util.img_as_ubyte, img_gray)

            # Canny edge detection using OpenCV
            img_canny = morphocut.Call(cv2.Canny, img_gray, 50, 100)

            # Dilate using OpenCV
            kernel = morphocut.Call(
                cv2.getStructuringElement, cv2.MORPH_ELLIPSE, (15, 15)
            )
            img_dilate = morphocut.Call(cv2.dilate, img_canny, kernel, iterations=2)

            # Close using OpenCV
            kernel = morphocut.Call(
                cv2.getStructuringElement, cv2.MORPH_ELLIPSE, (5, 5)
            )
            img_close = morphocut.Call(
                cv2.morphologyEx, img_dilate, cv2.MORPH_CLOSE, kernel, iterations=1
            )

            # Erode using OpenCV
            kernel = morphocut.Call(
                cv2.getStructuringElement, cv2.MORPH_ELLIPSE, (15, 15)
            )
            mask = morphocut.Call(cv2.erode, img_close, kernel, iterations=2)

            # Find objects
            regionprops = morphocut.image.FindRegions(
                mask, img_gray, min_area=1000, padding=10, warn_empty=name
            )

            # For an object, extract a vignette/ROI from the image
            roi_orig = morphocut.image.ExtractROI(img, regionprops, bg_color=255)

            # Generate an object identifier
            i = morphocut.stream.Enumerate()

            # morphocut.Call(print,i)

            # Define the ID of each object
            object_id = morphocut.str.Format("{name}_{i:d}", name=name, i=i)

            # morphocut.Call(print,object_id)

            # Define the name of each object
            object_fn = morphocut.str.Format(
                os.path.join(working_obj_path, "{name}.jpg"),
                name=object_id,
            )

            # Save the image of the object with its name
            morphocut.image.ImageWriter(object_fn, roi_orig)

            # Calculate features. The calculated features are added to the global_metadata.
            # Returns a Variable representing a dict for every object in the stream.
            meta = morphocut.contrib.zooprocess.CalculateZooProcessFeatures(
                regionprops, prefix="object_", meta=self.__global_metadata
            )

            # Get all the metadata
            json_meta = morphocut.Call(json.dumps, meta, sort_keys=True, default=str)


            # Add object_id to the metadata dictionary
            meta["object_id"] = object_id

            # Generate object filenames
            orig_fn = morphocut.str.Format("{object_id}.jpg", object_id=object_id)

            # Write objects to an EcoTaxa archive:
            # roi image in original color, roi image in grayscale, metadata associated with each object
            # morphocut.contrib.ecotaxa.EcotaxaWriter(self.__archive_fn, (orig_fn, roi_orig), meta)

            # Progress bar for objects
            morphocut.stream.TQDM(
                morphocut.str.Format("Object {object_id}", object_id=object_id)
            )

            id_json = morphocut.str.Format(
                '{{"object_id":"{object_id}"}}', object_id=object_id
            )


print("Morphocut's Pipeline has been created")