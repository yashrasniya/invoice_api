from pdf2image import convert_from_path,convert_from_bytes
import os

def pdf_to_jpg(pdf, output_folder='output_images', dpi=300):
    # Create output directory if it doesn't exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Convert PDF to list of images (one per page)
    # images = convert_from_path(pdf_path, dpi=dpi)
    images = convert_from_bytes(pdf,dpi=dpi)
    if images:
        image_path = os.path.join(output_folder, f'page_{i + 1}.jpg')
    # Save each image
    # for i, img in enumerate(images):
    #     image_path = os.path.join(output_folder, f'page_{i + 1}.jpg')
    #     img.save(image_path, 'JPEG')
    #     print(f"Saved: {image_path}")

