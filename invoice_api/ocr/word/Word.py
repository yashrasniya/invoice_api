class Coordinates(object):
    def __init__(self,**kwargs):
        self.x = kwargs["X"]*1000
        self.y = kwargs["Y"]*1000
    def __str__(self):
        return str(self.x)+','+str(self.y)
class Word:

    def __lt__(self, other):
        return self.get_tl().x < other.get_tl().x

    def __init__(self,**kwargs):

        self.detected_text=kwargs["Text"]
        self.bounding_box=kwargs["Geometry"]["BoundingBox"]
        self.polygon=kwargs["Geometry"]["Polygon"]
        self.coordinates=[]
        self.set_coordinates()
        self.header_type=None
    def __str__(self):
        return self.detected_text
    def get_tl(self):
        return self.coordinates[0]
    def get_tr(self):
        return self.coordinates[1]
    def get_br(self):
        return self.coordinates[2]
    def get_bl(self):
        return self.coordinates[3]
    def set_coordinates(self):
        for coordinates in self.polygon:
            self.coordinates.append(Coordinates(**coordinates))
    def __str__(self):
        return str(self.detected_text)
if __name__ == "__main__":
    from test import test_data

    t=[]
    for i in test_data.k:
        t.append(Word(**i))
    print(t)
