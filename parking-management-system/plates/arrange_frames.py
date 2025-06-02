import os
import shutil
import random

def organize_dataset(
    source_images_dir,
    source_labels_dir,
    output_base_dir,
    split_ratio=0.8,
    image_extensions=('.jpg'),
    label_extension='.txt'
):
    """
    Arranges images and their corresponding labels into train and val directories.

    Args:
        source_images_dir (str): Path to the directory containing all images.
        source_labels_dir (str): Path to the directory containing all labels.
        output_base_dir (str): Base directory where 'images' and 'labels'
                                (each with 'train' and 'val' subdirectories) will be created.
        split_ratio (float): The ratio of data to be used for training (e.g., 0.8 for 80% train, 20% val).
        image_extensions (tuple): A tuple of allowed image file extensions.
        label_extension (str): The extension of the label files.
    """

    # Create output directories
    output_images_train_dir = os.path.join(output_base_dir, 'images', 'train')
    output_images_val_dir = os.path.join(output_base_dir, 'images', 'val')
    output_labels_train_dir = os.path.join(output_base_dir, 'labels', 'train')
    output_labels_val_dir = os.path.join(output_base_dir, 'labels', 'val')

    for d in [
        output_images_train_dir,
        output_images_val_dir,
        output_labels_train_dir,
        output_labels_val_dir,
    ]:
        os.makedirs(d, exist_ok=True)

    # Get a list of all image files
    image_files = [
        f
        for f in os.listdir(source_images_dir)
        if os.path.isfile(os.path.join(source_images_dir, f))
        and f.lower().endswith(image_extensions)
    ]

    # Shuffle the image files to ensure random split
    random.shuffle(image_files)

    # Calculate split point
    split_point = int(len(image_files) * split_ratio)

    train_files = image_files[:split_point]
    val_files = image_files[split_point:]

    print(f"Total files found: {len(image_files)}")
    print(f"Training files: {len(train_files)}")
    print(f"Validation files: {len(val_files)}")

    # Function to copy files
    def copy_files(file_list, source_img_dir, source_lbl_dir, dest_img_dir, dest_lbl_dir):
        for img_filename in file_list:
            # Construct label filename
            name_without_ext = os.path.splitext(img_filename)[0]
            label_filename = name_without_ext + label_extension

            source_img_path = os.path.join(source_img_dir, img_filename)
            source_label_path = os.path.join(source_lbl_dir, label_filename)

            dest_img_path = os.path.join(dest_img_dir, img_filename)
            dest_label_path = os.path.join(dest_lbl_dir, label_filename)

            # Copy image
            if os.path.exists(source_img_path):
                shutil.copy2(source_img_path, dest_img_path)
            else:
                print(f"Warning: Image not found - {source_img_path}")

            # Copy label (if it exists)
            if os.path.exists(source_label_path):
                shutil.copy2(source_label_path, dest_label_path)
            else:
                print(f"Warning: Label not found for {img_filename} - {source_label_path}")

    print("\nCopying training files...")
    copy_files(
        train_files,
        source_images_dir,
        source_labels_dir,
        output_images_train_dir,
        output_labels_train_dir,
    )

    print("Copying validation files...")
    copy_files(
        val_files,
        source_images_dir,
        source_labels_dir,
        output_images_val_dir,
        output_labels_val_dir,
    )

    print("\nDataset organization complete!")
    print(f"Images are in: {os.path.join(output_base_dir, 'images')}")
    print(f"Labels are in: {os.path.join(output_base_dir, 'labels')}")


if __name__ == "__main__":
    # --- Configuration ---
    # IMPORTANT: Update these paths to your actual directories
    SOURCE_IMAGES_DIR = "./"  # e.g., "my_dataset/images"
    SOURCE_LABELS_DIR = "./"  # e.g., "my_dataset/labels"
    OUTPUT_BASE_DIR = "./arranged_dataset"  # e.g., "my_dataset_split"

    TRAIN_VAL_SPLIT_RATIO = 0.8  # 80% for training, 20% for validation

    # Example usage:
    # Make sure to create dummy directories and files for testing,
    # or point to your actual dataset.
    #
    # Example structure before running the script:
    # my_dataset/
    # ├── images/
    # │   ├── img1.jpg
    # │   ├── img2.png
    # │   └── img3.jpeg
    # └── labels/
    #     ├── img1.txt
    #     ├── img2.txt
    #     └── img3.txt

    # After running, it will create:
    # my_dataset_split/
    # ├── images/
    # │   ├── train/
    # │   │   ├── imgX.jpg
    # │   │   └── ...
    # │   └── val/
    # │       ├── imgY.jpg
    # │       └── ...
    # └── labels/
    #     ├── train/
    #     │   ├── imgX.txt
    #     │   └── ...
    #     └── val/
    #         ├── imgY.txt
    #         └── ...

    # You can uncomment and use the following lines for testing with dummy data
    # if you don't have a dataset ready.
    # ---------------------------------------------------------------------
    # os.makedirs(SOURCE_IMAGES_DIR, exist_ok=True)
    # os.makedirs(SOURCE_LABELS_DIR, exist_ok=True)
    #
    # # Create some dummy image and label files
    # for i in range(1, 11): # Create 10 dummy files
    #     with open(os.path.join(SOURCE_IMAGES_DIR, f"image_{i}.jpg"), "w") as f:
    #         f.write(f"dummy image {i}")
    #     with open(os.path.join(SOURCE_LABELS_DIR, f"image_{i}.txt"), "w") as f:
    #         f.write(f"dummy label for image {i}")
    # print("Created dummy data for testing.")
    # ---------------------------------------------------------------------

    organize_dataset(
        source_images_dir=SOURCE_IMAGES_DIR,
        source_labels_dir=SOURCE_LABELS_DIR,
        output_base_dir=OUTPUT_BASE_DIR,
        split_ratio=TRAIN_VAL_SPLIT_RATIO,
    )