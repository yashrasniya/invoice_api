import random
import binascii
import base64
from django.core.files.base import ContentFile


def image_add_db(file_array, validated_data,instance=None):
    for i in file_array:
        if validated_data.get(i, ''):

            image_data = validated_data.get(i)
            if image_data=='none':
                file_array[i].delete()
                # instance.save()
            else:
                try:
                    img_formate=image_data.split(';base64,')[0].split('/')[1]
                    print(img_formate)
                    data = ContentFile(base64.b64decode(image_data.split(',')[1]))
                except binascii.Error as e:
                    print(e)
                    return binascii.Error(f'{i} send data is in incorrect format it should be in bash 64')
                file_name = str(random.random()) + '.' + str(img_formate)
                file_array[i].save(file_name, data, save=True)
