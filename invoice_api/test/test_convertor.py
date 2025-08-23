import json
import unittest

default_path="invoice_api/test/test_data/json/"

class testocr(unittest.TestCase):
    def file_setup(self, filename):
        with open(f"{default_path}{filename}", "r") as f:
            data = json.load(f)
        self.data = data

    def test_convertor(self):
        from reportlab.pdfgen import canvas
        self.file_setup("computer_gen_one_item.json")
        canvas_obj= canvas.Canvas("test.pdf")
        t = []
        for i in self.data:
            if i["BlockType"] == "LINE":
                # t.append(Word(**i))
                # print(i)
                coordinates = i.get('Geometry').get('Polygon')[-1]
                print((coordinates.get("X"), coordinates.get("Y"), i.get("Text")))
                canvas_obj.setFontSize(7)
                canvas_obj.drawString(coordinates.get("X")*595.276, 841.89-coordinates.get("Y") *841.89, i.get("Text"))
        canvas_obj.save()
        423.145
        77.11923230588434

    def test_pdf(self):
        import fitz  # PyMuPDF
        from reportlab.pdfgen import canvas
        import yaml
        import random

        # Open the source PDF
        doc = fitz.open("SBS BILL.pdf")
        page = doc[0]  # first page
        width, height = page.rect.width, page.rect.height
        canvas_obj = canvas.Canvas("test.pdf", pagesize=(width, height))
        print(width,height)
        drawings_array = []
        for page_num, page in enumerate(doc, start=1):
            print(f"Page {page_num}:")

            # Get drawings (lines, rectangles, curves, etc.)
            drawings = page.get_drawings()
            # print(page.get_text())


            for d in drawings:
                for item in d["items"]:
                    random_number = str(round(random.random() * 1000))

                    if item[0] == "l":  # line
                        x1, y1,  = item[1]
                        x2, y2  = item[2]
                        print(f" Line from ({x1}, {y1}) to ({x2}, {y2})")
                        canvas_obj.line(x1,height- y1, x2, height - y2)
                        obj = {
                            "type": 'line',
                            "x":x1,
                            "y":height- y1,
                            "x2": x2,
                            "y2": height - y2,
                            "label": random_number
                        }
                        drawings_array.append({random_number:obj})

                    if item[0] == "re":  # rectangle
                        x, y, w, h = item[1]

                        obj = {
                            "type": 'rectangles',
                            "x": x,
                            "y":  height - y,
                            "width":  w-x,
                            "height":  y-h,
                            "label": random_number
                        }
                        drawings_array.append({random_number:obj})
                        print(item)
                        print(f" Rectangle at ({x}, {y}), w={w}, h={h}")
                        canvas_obj.setLineWidth(d["width"])
                        canvas_obj.rect(x, height - y, w-x, y-h)

                        print("   Color:", d["color"])
                        print("   Width:", d["width"])
            for d in page.get_text_words():
                x,y=  d[0],d[1]
                canvas_obj.setFontSize(7)
                canvas_obj.drawString(x,height-y,d[4])
        data = {"drawings_array":drawings_array}

        with open("output.yaml", "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        # Save the new PDF
        canvas_obj.save()


