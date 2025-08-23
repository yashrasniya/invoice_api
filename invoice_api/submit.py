import logging
from io import BytesIO

import requests
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.utils import ImageReader


from PIL import Image

from invoice.models import Font
logger = logging.getLogger(__name__)

class Submit:
    font_size = 9
    font = 'Times-Roman'

    def __init__(self, data, pdf_name="bill.pdf", bill_image=None):
        self.data = data
        self.pdf_name = pdf_name
        self.bill_image = bill_image
        self.add_fonts()
        self.canvas_obj = canvas.Canvas(pdf_name)
        self.canvas_obj.setTitle(pdf_name)
        self.page_width = 595.276
        self.page_height = 841.89


    def add_fonts(self):
        for i in Font.objects.all():
            if i.name == "default":
                self.font = i.name
            pdfmetrics.registerFont(TTFont(i.name, i.font.path))

    def add_template(self):
        """Draws the bill template image for the current page."""
        if self.bill_image:
            self.canvas_obj.drawImage(
                self.bill_image,
                0,
                0,
                width=self.page_width,
                height=self.page_height
            )

    def draw_polygon(self,obj):
        """
            Draws a Polygon object on the canvas.
            :param obj: Polygon instance
            """
        if not obj.points:
            return  # nothing to draw

        path = self.canvas_obj.beginPath()
        x0, y0 = obj.points[0]
        path.moveTo(x0, y0)

        # draw remaining lines
        for (x, y) in obj.points[1:]:
            path.lineTo(x, y)

        if obj.closed:
            path.close()

        # Apply styles
        self.canvas_obj.setLineWidth(obj.line_width)
        self.canvas_obj.setStrokeColor(
            getattr(colors, obj.stroke, colors.black)
            if isinstance(obj.stroke, str) else obj.stroke
        )
        if isinstance(obj.stroke, str):
            if obj.stroke.startswith("#"):  # hex color
                self.canvas_obj.setStrokeColor(colors.HexColor(obj.stroke))
            else:  # named color like "red"
                self.canvas_obj.setStrokeColor(getattr(colors, obj.stroke, colors.black))
        else:
            self.canvas_obj.setStrokeColor(obj.stroke)
        if obj.fill:
            self.canvas_obj.setFillColor(
                getattr(colors, obj.fill, colors.transparent)
                if isinstance(obj.fill, str) else obj.fill
            )
        stroke = obj.raw.get('stroke',1)
        if obj.src:
            points = obj.points
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]

            x = min(xs)
            y = min(ys)
            width = max(xs) - x
            height = max(ys) - y
            try:
                response = requests.get(obj.src)
                response.raise_for_status()

                # Wrap in BytesIO
                img_data = BytesIO(response.content)
                # Use ImageReader for ReportLab
                img = ImageReader(img_data)
                self.canvas_obj.drawImage(
                    img,
                    x, y,
                    width=width,
                    height=height
                )
            except Exception as e:
                logger.info(e)
        else:
            self.canvas_obj.drawPath(path, stroke=stroke, fill=1 if obj.fill else 0)
            # self.canvas_obj.drawString(obj.x, obj.y, str(obj.label))

    def draw_line(self, obj):
        """
        Draws a Line object on the canvas.
        :param obj: Line instance
        """
        path = self.canvas_obj.beginPath()
        path.moveTo(obj.x1, obj.y1)
        path.lineTo(obj.x2, obj.y2)

        # Apply styles
        self.canvas_obj.setLineWidth(obj.line_width)

        if isinstance(obj.stroke, str):
            if obj.stroke.startswith("#"):  # hex color
                self.canvas_obj.setStrokeColor(colors.HexColor(obj.stroke))
            else:  # named color like "red"
                self.canvas_obj.setStrokeColor(
                    getattr(colors, obj.stroke, colors.black)
                )
        else:
            self.canvas_obj.setStrokeColor(obj.stroke)

        stroke = obj.raw.get('stroke', 1)
        self.canvas_obj.drawPath(path, stroke=stroke, fill=0)
        # self.canvas_obj.drawString(obj.x2, obj.y2, str(obj.label))

    def draw_string(self,obj):
        font = obj.font if obj.font else self.font
        self.canvas_obj.setFont(font, self.font_size)
        obj.add_suffix()
        obj.add_prefix()

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
                    font_size = obj.next_line.get("font_size",
                                                  self.font_size - 2) if obj.next_line else self.font_size - 2
                    self.canvas_obj.setFontSize(font_size)
                self.canvas_obj.drawString(x, y, ' '.join(draw_value))
        else:
            self.canvas_obj.drawString(obj.x, obj.y, str(obj.value))



    def draw_header_data(self):
        total_items = len(self.data)

        for page_start in range(0,total_items):
            # Start new page
            self.add_template()
            self.canvas_obj.setFontSize(self.font_size)
            page_data = self.data[page_start]
            for obj in page_data.collect_all_data():
                if obj.type()=="Polygon":
                    self.draw_polygon(obj)
                elif obj.type()=="Line":
                    self.draw_line(obj)
                else:
                    self.draw_string(obj)


            # Finish page and start a new one if more data exists
            self.canvas_obj.showPage()

        return self.canvas_obj.getpdfdata()

