# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# PDX-License-Identifier: MIT-0 (For details, see https://github.com/awsdocs/amazon-rekognition-developer-guide/blob/master/LICENSE-SAMPLECODE.)
import io

import boto3
from PIL import Image


def detect_text(photo, bucket):

    session = boto3.Session(profile_name='default')
    client = session.client('rekognition')

    image_path = 'bill_1.jpg'
    image = Image.open(image_path)

    stream = io.BytesIO()
    image.save(stream, format="JPEG")
    image_binary = stream.getvalue()
    response = client.detect_text(Image={'Bytes':image_binary})

    textDetections = response['TextDetections']
    print(textDetections)
    # print('Detected text\n----------')
    # for text in textDetections:
    #     print('Detected text:' + text['DetectedText'])
    #     print('Confidence: ' + "{:.2f}".format(text['Confidence']) + "%")
    #     print('Id: {}'.format(text['Id']))
    #     if 'ParentId' in text:
    #         print('Parent Id: {}'.format(text['ParentId']))
    #     print('Type:' + text['Type'])
    #     print()
    return len(textDetections)

def main():
    bucket = 'bucket-name'
    photo = 'photo-name'
    text_count = detect_text(photo, bucket)
    # print("Text detected: " + str(text_count))

if __name__ == "__main__":
    main()