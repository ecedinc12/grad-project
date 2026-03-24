import os
import json
import argparse

def convert_coco_to_yolo(coco_dir="/tmp/dataset"):
    # Output from BasicWriter usually has a JSON file like bounding_box_2d_tight.json or instances_default.json
    # BasicWriter with format="coco" outputs annotations in instances_default.json usually
    coco_json_path = os.path.join(coco_dir, "instances_default.json")
    
    if not os.path.exists(coco_json_path):
        print(f"Warning: COCO JSON not found at {coco_json_path}. Ensure BasicWriter has output the COCO format.")
        return

    with open(coco_json_path, "r") as f:
        coco_data = json.load(f)

    # Dictionary to map image_id to its dict for easy access
    images_info = {img["id"]: img for img in coco_data["images"]}
    
    # Process annotations
    for ann in coco_data["annotations"]:
        image_id = ann["image_id"]
        category_id = ann["category_id"]
        
        # COCO BBox format is [x_min, y_min, width, height]
        # YOLO BBox format is [x_center, y_center, width, height] normalized by image width and height
        bbox = ann["bbox"]
        x_min, y_min, width, height = bbox
        
        img_info = images_info[image_id]
        img_width = img_info["width"]
        img_height = img_info["height"]
        
        x_center = x_min + (width / 2.0)
        y_center = y_min + (height / 2.0)
        
        norm_x_center = x_center / img_width
        norm_y_center = y_center / img_height
        norm_width = width / img_width
        norm_height = height / img_height
        
        yolo_line = f"{category_id} {norm_x_center:.6f} {norm_y_center:.6f} {norm_width:.6f} {norm_height:.6f}\n"
        
        # Usually file_name is something like 'rgb_0000.png'
        # We need to write to the same base name with .txt extension
        img_filename = img_info["file_name"]
        txt_filename = os.path.splitext(img_filename)[0] + ".txt"
        txt_filepath = os.path.join(coco_dir, txt_filename)
        
        with open(txt_filepath, "a") as txt_f:
            txt_f.write(yolo_line)
            
    print(f"Successfully converted COCO annotations to YOLO format in {coco_dir}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert COCO JSON to YOLO format.")
    parser.add_argument("--dir", type=str, default="/tmp/dataset", help="Directory containing the COCO JSON and images.")
    
    args = parser.parse_args()
    convert_coco_to_yolo(args.dir)
