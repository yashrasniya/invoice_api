from reportlab.pdfgen import canvas
from PIL import Image

class Submit:
    font_size=9
    def __init__(self,data,pdf_name="bill.pdf",bill_image="template.jpg"):
        self.data=data
        self.canvas_obj = canvas.Canvas(pdf_name)
        self.canvas_obj.drawImage("aaa.jpg", 0, 00, width=595.276, height=841.89)
        self.canvas_obj.setFontSize(self.font_size)



    def draw_header_data(self):
        for obj in self.data:
            self.canvas_obj.setFontSize(self.font_size)
            obj.add_suffix()
            if obj.font_size:
                self.canvas_obj.setFontSize(obj.font_size)
            if obj.limit and len(obj.value)>obj.limit:
                text_list=obj.value.split(' ')
                draw_value=[]
                text_len=0
                x=obj.x
                y=obj.y
                line=1
                for text in text_list:
                    draw_value.append(text)
                    text_len+=len(text)+1
                    if text_len>obj.limit and line < obj.no_lines:
                        self.canvas_obj.drawString(x, y, ' '.join(draw_value[:-1]))
                        draw_value.clear()
                        draw_value.append(text)
                        text_len=len(text)+1
                        x=obj.next_line.get("x",obj.x)
                        font_size=obj.next_line.get("font_size",self.font_size)
                        self.canvas_obj.setFontSize(font_size)
                        y=y-obj.next_line.get("gap",15)
                        line+=1
                if text_len>0:
                    if text_len>obj.limit:
                        font_size = obj.next_line.get("font_size", self.font_size - 2) if obj.next_line else self.font_size - 2
                        self.canvas_obj.setFontSize(font_size)
                    self.canvas_obj.drawString(x, y, ' '.join(draw_value))
                continue
            # if obj.limit and str(obj.value) > obj.limit:
            #     font_size = obj.next_line.get("font_size", self.font_size - 2) if obj.next_line else self.font_size - 2
            #     self.canvas_obj.setFontSize(font_size)
            self.canvas_obj.drawString(obj.x, obj.y, str(obj.value))
        return self.canvas_obj.getpdfdata()


