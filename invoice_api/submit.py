from reportlab.pdfgen import canvas
from PIL import Image

class Submit:
    font_size = 9

    def __init__(self, data, pdf_name="bill.pdf", bill_image="template.jpg"):
        self.data = data
        self.pdf_name = pdf_name
        self.bill_image = bill_image
        self.canvas_obj = canvas.Canvas(pdf_name)
        self.page_width = 595.276
        self.page_height = 841.89

    def add_template(self):
        """Draws the bill template image for the current page."""
        self.canvas_obj.drawImage(
            self.bill_image,
            0,
            0,
            width=self.page_width,
            height=self.page_height
        )

    def draw_header_data(self):
        total_items = len(self.data)

        for page_start in range(0,total_items):
            # Start new page
            self.add_template()
            self.canvas_obj.setFontSize(self.font_size)
            page_data = self.data[page_start]
            for obj in page_data:
                self.canvas_obj.setFontSize(self.font_size)
                obj.add_suffix()

                if obj.font_size:
                    self.canvas_obj.setFontSize(obj.font_size)

                if obj.limit and obj.value and len(obj.value) > obj.limit:
                    text_list = obj.value.split(' ')
                    draw_value = []
                    text_len = 0
                    x = obj.x
                    y = obj.y
                    line = 1

                    for text in text_list:
                        draw_value.append(text)
                        text_len += len(text) + 1
                        if text_len > obj.limit and line < obj.no_lines:
                            self.canvas_obj.drawString(x, y, ' '.join(draw_value[:-1]))
                            draw_value.clear()
                            draw_value.append(text)
                            text_len = len(text) + 1
                            x = obj.next_line.get("x", obj.x)
                            font_size = obj.next_line.get("font_size", self.font_size)
                            self.canvas_obj.setFontSize(font_size)
                            y -= obj.next_line.get("gap", 15)
                            line += 1

                    if text_len > 0:
                        if text_len > obj.limit:
                            font_size = obj.next_line.get("font_size", self.font_size - 2) if obj.next_line else self.font_size - 2
                            self.canvas_obj.setFontSize(font_size)
                        self.canvas_obj.drawString(x, y, ' '.join(draw_value))
                    continue

                self.canvas_obj.drawString(obj.x, obj.y, str(obj.value))

            # Finish page and start a new one if more data exists
            self.canvas_obj.showPage()

        return self.canvas_obj.getpdfdata()

