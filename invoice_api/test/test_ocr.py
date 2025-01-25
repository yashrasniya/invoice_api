import json
import unittest

from ocr.analysis_text.process_output_text import ProcessOutputText
from ocr.word.Word import Word

default_path="invoice_api/test/test_data/json/"

class testocr(unittest.TestCase):
    def test_find_personal_info(self):
        t = []
        data=[{"DetectedText": "Invoice No.", "Type": "LINE", "Id": 16, "Confidence": 98.98226928710938, "Geometry": {
         "BoundingBox": {"Width": 0.0742187649011612, "Height": 0.0082855224609375, "Left": 0.0839843600988388,
                         "Top": 0.24787521362304688},
         "Polygon": [{"X": 0.0839843600988388, "Y": 0.24787521362304688}, {"X": 0.158203125, "Y": 0.24787521362304688},
                     {"X": 0.158203125, "Y": 0.2561607360839844}, {"X": 0.0839843600988388, "Y": 0.2561607360839844}]}}]
        for i in self.data:
            if i["BlockType"] == "LINE":
                t.append(Word(**i))
        # print(t)
        obj=ProcessOutputText(t)
        obj.find_personal_info()
        obj.process_personal_info()
        print([str(i) for i in obj.personal_info_raw_data])
        print({i:[str(i) for i in obj.personal_info_data[i]] for i in obj.personal_info_data})

    def table_headers(self,path):
        self.file_setup(path)
        t = []
        for i in self.data:
            if i["BlockType"]=="WORD" :
                t.append(Word(**i))
        obj=ProcessOutputText(t)
        obj.find_table_headers()
        obj.process_table_headers()
        row=obj.process_table_data()
        row=obj.remove_duplicate(row)
        row=obj.process_missing_items(row)


        # print([str(i) for i in obj.table_headers])
        print({i.name:[str(i) for i in obj.table_data[i]] for i in obj.table_data})
        for l,i in enumerate(row):
            for j in i:
                print(j, end=" ,")
            print("\n")
            # print(l)

    def file_setup(self,filename):
        with open(f"{default_path}{filename}", "r") as f:
            data = json.load(f)
        self.data = data
    def test_click_file(self):
        self.table_headers("click_img.json")
    def test_computer_gen_one_item(self):
        self.table_headers("computer_gen_one_item.json")
    def test_bill_with_5_iteam(self):
        self.table_headers("bill_with_5_iteam.json")

