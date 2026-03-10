"""
Data Writer Module for Industrial Safety Synthetic Data Pipeline.

This module implements a custom Replicator Writer for exporting annotations
in KITTI/COCO formats with proper error handling and VRAM safety.
"""

import os
import json
import tempfile
import shutil
from typing import Dict, List, Any, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image
import omni.replicator.core as rep
from omni.replicator.core import Writer, BackendDispatch


class SafetyDatasetWriter(Writer):
    """
    Custom Writer for safety dataset annotations.
    
    Lifecycle managed by omni.replicator.core.WriterRegistry:
        1. WriterRegistry.register(SafetyDatasetWriter)
        2. writer = WriterRegistry.get("SafetyDatasetWriter")   # calls __init__()
        3. writer.initialize(output_dir=..., class_mapping=...) # real setup
        4. writer.attach([render_product])                      # binds annotators
    """
    
    def __init__(self):
        """Bare-bones constructor required by WriterRegistry.get()."""
        super().__init__()
        # Attributes are populated later in initialize()
        self.output_dir = None
        self.class_mapping = {}
        self.image_format = "png"
        self.annotation_format = "kitti"
        self.rgb_dir = ""
        self.annotations_dir = ""
        self.metadata_dir = ""
        self.frame_count = 0
        self.executor = ThreadPoolExecutor(max_workers=4)
    
    def initialize(self,
                   output_dir: str = "output/dataset_v1",
                   class_mapping: Dict[str, int] = None,
                   image_format: str = "png",
                   annotation_format: str = "kitti",
                   **kwargs) -> None:
        """
        Called by Replicator after construction to pass user parameters.
        
        Args:
            output_dir: Base output directory.
            class_mapping: Dictionary mapping class names to integer IDs.
            image_format: Image file format (png, jpg).
            annotation_format: Annotation format (kitti, coco).
        """
        self.output_dir = output_dir
        self.class_mapping = class_mapping or {"worker": 0, "forklift": 1, "helmet": 2, "no_helmet": 3}
        self.image_format = image_format.lower()
        self.annotation_format = annotation_format.lower()
        
        # Create output directories
        self.rgb_dir = os.path.join(output_dir, "rgb")
        self.annotations_dir = os.path.join(output_dir, "annotations")
        self.metadata_dir = os.path.join(output_dir, "metadata")
        
        for directory in [self.rgb_dir, self.annotations_dir, self.metadata_dir]:
            os.makedirs(directory, exist_ok=True)
        
        # Reset frame counter
        self.frame_count = 0
        
        # Tell Replicator which annotators this writer needs.
        # These keys will appear in the `data` dict passed to write().
        self.annotators = [
            rep.AnnotatorRegistry.get_annotator("rgb"),
            rep.AnnotatorRegistry.get_annotator("bounding_box_2d_tight"),
            rep.AnnotatorRegistry.get_annotator("semantic_segmentation"),
        ]
        
        print(f"[SafetyDatasetWriter] Initialized with output directory: {output_dir}")
        print(f"[SafetyDatasetWriter] Class mapping: {self.class_mapping}")
        print(f"[SafetyDatasetWriter] Annotation format: {annotation_format}")

    def _ensure_safe_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deep copy data and ensure it is on CPU (numpy) to avoid
        threading race conditions with the simulation backend.
        """
        safe_data = {}
        import copy
        
        for key, value in data.items():
            if isinstance(value, dict) and "data" in value:
                # Handle annotator data block
                safe_block = copy.copy(value)
                
                # Check for numpy array
                if hasattr(value["data"], "copy"):
                     # Force copy to detach from shared memory/backend buffer
                    safe_block["data"] = value["data"].copy()
                # Check for torch tensor (if backend returns tensor)
                elif hasattr(value["data"], "cpu"):
                    safe_block["data"] = value["data"].cpu().numpy()
                
                safe_data[key] = safe_block
            else:
                # Metadata or simple types
                safe_data[key] = value
                
        return safe_data
    
    def write(self, data: Dict[str, Any]) -> None:
        """
        Write frame data to disk.
        
        Called automatically by Replicator on each orchestrator.step().
        
        Args:
            data: Dictionary containing frame data from annotators.
        """
        try:
            # Replicator may pass annotator outputs directly as numpy arrays
            # or as dicts with a "data" key. Normalise into {"data": ...} form.
            normalised: Dict[str, Any] = {}
            for key, value in data.items():
                if isinstance(value, dict) and "data" in value:
                    normalised[key] = value
                elif hasattr(value, "shape"):  # numpy array
                    normalised[key] = {"data": value}
                elif isinstance(value, dict):
                    normalised[key] = value
                else:
                    normalised[key] = {"data": value}

            rgb_data = normalised.get("rgb")
            if rgb_data is None or ("data" in rgb_data and rgb_data["data"] is None):
                return

            # CRITICAL: Ensure data is deep copied and on CPU before passing to thread
            safe_data = self._ensure_safe_data(normalised)

            # Submit to thread pool
            self.executor.submit(self._process_and_write_frame, safe_data, self.frame_count)
            
            self.frame_count += 1
            if self.frame_count % 100 == 0:
                print(f"[SafetyDatasetWriter] Queued {self.frame_count} frames")
            
        except Exception as e:
            print(f"[SafetyDatasetWriter] Error scheduling frame write: {e}")
            import traceback
            traceback.print_exc()

    def _process_and_write_frame(self, data: Dict[str, Any], frame_number: int) -> None:
        """
        Internal method to process and write frame data (runs in thread).
        """
        try:
            rgb_data = data.get("rgb", {})
            bbox_data = data.get("bounding_box_2d_tight", {})
            
            # Generate unique frame ID based on count
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            frame_id = f"frame_{frame_number:06d}_{timestamp}"
            
            # Get actual resolution from RGB data for clamping
            img_width = 1920
            img_height = 1080
            
            if "data" in rgb_data and hasattr(rgb_data["data"], "shape"):
                shape = rgb_data["data"].shape
                if len(shape) >= 2:
                    img_height, img_width = shape[:2]

            # Pass resolution explicitly to annotation writer
            resolution = (img_width, img_height)

            # Write RGB image
            rgb_success = self._write_rgb(rgb_data, frame_id)
            
            # Write annotations
            if self.annotation_format == "kitti":
                anno_success = self._write_kitti_annotations(bbox_data, frame_id, resolution)
            elif self.annotation_format == "coco":
                anno_success = self._write_coco_annotations(bbox_data, frame_id)
            else:
                print(f"[SafetyDatasetWriter] Unknown annotation format: {self.annotation_format}")
                anno_success = False
            
            # Write metadata
            self._write_metadata(data, frame_id, frame_number)

        except Exception as e:
            print(f"[SafetyDatasetWriter] Error writing frame {frame_number}: {e}")
    
    def _write_rgb(self, rgb_data: Dict[str, Any], frame_id: str) -> bool:
        """
        Write RGB image to disk.
        
        Args:
            rgb_data: RGB annotator data.
            frame_id: Unique frame identifier.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            if "data" not in rgb_data:
                print("[SafetyDatasetWriter] No RGB data in frame")
                return False
            
            # Convert to PIL Image
            image_array = rgb_data["data"]
            if len(image_array.shape) == 3:
                # Replicator's rgb annotator returns RGBA (4 channels) — drop alpha
                if image_array.shape[2] == 4:
                    image_array = image_array[:, :, :3]
                
                if image_array.shape[2] != 3:
                    print(f"[SafetyDatasetWriter] Unexpected channel count: {image_array.shape[2]}")
                    return False
                
                image = Image.fromarray(image_array)
            else:
                print(f"[SafetyDatasetWriter] Unexpected image shape: {image_array.shape}")
                return False
            
            # Save image with atomic write
            filename = f"{frame_id}.{self.image_format}"
            filepath = os.path.join(self.rgb_dir, filename)
            
            # Atomic write: write to temp file then rename
            with tempfile.NamedTemporaryFile(
                suffix=f".{self.image_format}", 
                dir=self.rgb_dir,
                delete=False
            ) as tmp_file:
                tmp_path = tmp_file.name
                image.save(tmp_path)
                shutil.move(tmp_path, filepath)
            
            return True
            
        except Exception as e:
            print(f"[SafetyDatasetWriter] Error writing RGB image: {e}")
            return False
    
    def _write_kitti_annotations(self, bbox_data: Dict[str, Any], frame_id: str, resolution: tuple = (1920, 1080)) -> bool:
        """
        Write annotations in KITTI format.
        
        Args:
            bbox_data: Bounding box annotator data.
            frame_id: Unique frame identifier.
            resolution: (width, height) of the image.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            if "data" not in bbox_data:
                # This is acceptable for negative samples
                # Ensure we create an empty file
                lines = []
            else:
                bboxes = bbox_data["data"]
                class_names = bbox_data.get("info", {}).get("classNames", [])
                
                # Prepare KITTI lines
                lines = []
                
                img_width, img_height = resolution
                
                for i, bbox in enumerate(bboxes):
                    if len(bbox) < 4:
                        continue
                    
                    # Extract coordinates
                    x1, y1, x2, y2 = bbox[:4]
                    
                    # Clamp to image bounds (safety check)
                    x1 = max(0, min(x1, img_width - 1))
                    y1 = max(0, min(y1, img_height - 1))
                    x2 = max(0, min(x2, img_width - 1))
                    y2 = max(0, min(y2, img_height - 1))
                    
                    # Check for microscopic boxes
                    if (x2 - x1) < 5 or (y2 - y1) < 5:
                        continue
                    
                    # Get class name and ID
                    class_name = class_names[i] if i < len(class_names) else "unknown"
                    class_id = self.class_mapping.get(class_name, -1)
                    
                    if class_id == -1:
                        continue
                    
                    # KITTI format: class_name, truncation, occlusion, alpha, 
                    # bbox_left, bbox_top, bbox_right, bbox_bottom, 
                    # dimensions, location, rotation_y, score
                    # We'll fill with placeholders for unused fields
                    line = (f"{class_name} 0.00 0 0.0 "
                           f"{x1:.2f} {y1:.2f} {x2:.2f} {y2:.2f} "
                           f"0 0 0 0 0 0 0 0.00")
                    lines.append(line)
            
            # Write to file
            filename = f"{frame_id}.txt"
            filepath = os.path.join(self.annotations_dir, filename)
            
            with tempfile.NamedTemporaryFile(
                mode='w', 
                suffix='.txt',
                dir=self.annotations_dir,
                delete=False
            ) as tmp_file:
                tmp_path = tmp_file.name
                tmp_file.write('\n'.join(lines))
                shutil.move(tmp_path, filepath)
            
            return True
            
        except Exception as e:
            print(f"[SafetyDatasetWriter] Error writing KITTI annotations: {e}")
            return False
    
    def _write_coco_annotations(self, bbox_data: Dict[str, Any], frame_id: str) -> bool:
        """
        Write annotations in COCO format (simplified).
        Note: This is a simplified implementation.
        
        Args:
            bbox_data: Bounding box annotator data.
            frame_id: Unique frame identifier.
            
        Returns:
            True if successful, False otherwise.
        """
        # For now, we'll implement KITTI only
        print("[SafetyDatasetWriter] COCO format not yet implemented, using KITTI")
        return self._write_kitti_annotations(bbox_data, frame_id)
    
    def _write_metadata(self, data: Dict[str, Any], frame_id: str, frame_number: int) -> bool:
        """
        Write metadata JSON for the frame.
        
        Args:
            data: Complete frame data.
            frame_id: Unique frame identifier.
            frame_number: The sequential frame number.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            metadata = {
                "frame_id": frame_id,
                "timestamp": datetime.now().isoformat(),
                "frame_number": frame_number,
                "is_negative_sample": data.get("is_negative_sample", False),
                "camera_pose": data.get("camera_pose", {}),
                "time_of_day": data.get("time_of_day", "unknown"),
                "has_annotations": "bounding_box_2d_tight" in data
            }
            
            filename = f"{frame_id}_metadata.json"
            filepath = os.path.join(self.metadata_dir, filename)
            
            with tempfile.NamedTemporaryFile(
                mode='w', 
                suffix='.json',
                dir=self.metadata_dir,
                delete=False
            ) as tmp_file:
                tmp_path = tmp_file.name
                json.dump(metadata, tmp_file, indent=2)
                shutil.move(tmp_path, filepath)
            
            return True
            
        except Exception as e:
            print(f"[SafetyDatasetWriter] Error writing metadata: {e}")
            return False
    
    def on_shutdown(self) -> None:
        """
        Cleanup on writer shutdown.
        """
        print(f"[SafetyDatasetWriter] Shutting down. Waiting for pending writes...")
        self.executor.shutdown(wait=True)
        print(f"[SafetyDatasetWriter] Shutdown complete. Total frames processed: {self.frame_count}")
        
        # Write summary file
        summary = {
            "total_frames": self.frame_count,
            "output_directory": self.output_dir,
            "class_mapping": self.class_mapping,
            "completion_time": datetime.now().isoformat()
        }
        
        summary_path = os.path.join(self.output_dir, "generation_summary.json")
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"[SafetyDatasetWriter] Summary written to: {summary_path}")


if __name__ == "__main__":
    """
    Test the SafetyDatasetWriter module.
    """
    print("=== SafetyDatasetWriter Module Test ===")
    
    # Create a test output directory
    test_output_dir = "output/test_writer"
    
    # Define class mapping
    class_mapping = {
        "worker": 0,
        "forklift": 1,
        "helmet": 2,
        "no_helmet": 3
    }
    
    # Initialize writer
    writer = SafetyDatasetWriter(
        output_dir=test_output_dir,
        class_mapping=class_mapping,
        annotation_format="kitti"
    )
    
    # Create mock data
    mock_data = {
        "rgb": {
            "data": np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8),
            "channel": "rgb",
            "width": 1920,
            "height": 1080
        },
        "bounding_box_2d_tight": {
            "data": [
                [100, 200, 300, 400],  # x1, y1, x2, y2
                [500, 600, 700, 800]
            ],
            "info": {
                "classNames": ["worker", "forklift"]
            },
            "width": 1920,
            "height": 1080
        },
        "is_negative_sample": False,
        "camera_pose": {"x": 0, "y": 0, "z": 5},
        "time_of_day": "day"
    }
    
    # Test writing
    print("\n1. Testing data writing...")
    writer.write(mock_data)
    
    # Test shutdown
    print("\n2. Testing shutdown...")
    writer.on_shutdown()
    
    print("\n=== Test completed successfully ===")
    print(f"Check output in: {test_output_dir}")
