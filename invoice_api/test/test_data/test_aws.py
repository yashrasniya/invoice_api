import io
import json
import unittest

import boto3
from PIL import Image

default_path= "invoice_api/test/test_data/img/"

def detect_text(image_path):

    session = boto3.Session(profile_name='default')
    client = session.client('textract')


    image = Image.open(image_path)

    stream = io.BytesIO()
    image.save(stream, format="png")
    image_binary = stream.getvalue()
    response = client.detect_document_text(Document={'Bytes':image_binary})

    textDetections = response['Blocks']
    with open(f"invoice_api/test/test_data/json/{image_path.split('/')[-1].split('.')[0]}.json", "w", encoding='utf-8') as f:
        f.write(json.dumps(textDetections, indent=4))
    return len(textDetections)


class test_aws(unittest.TestCase):

    def test_aws(self):
        image_path = 'click_img.jpeg'
        detect_text(default_path + image_path)
    def test_bill_with_5_iteam(self):
        image_path = 'bill_with_5_iteam.png'
        detect_text(default_path + image_path)