import yaml
import copy
from submit import Submit
class Point:

    def __init__(self,title,x=None,y=None,label=None,value=None,**kwargs):
        self.title=title
        self.x=x
        self.y=y
        self.value=value
        self.label=label
        self.raw=kwargs
        self.next_line=kwargs.get('next_line',None)
        self.font_size=kwargs.get('font_size',None)
        self.limit=kwargs.get('limit',None)
        self.no_lines=kwargs.get('no_lines',1)
        self.suffix=kwargs.get('suffix',None)

    def add_suffix(self):
        if self.suffix is not None:
            self.value=str(self.value)+self.suffix


    def __str__(self):
        return self.title

def get_yaml_data(name):
    with open(name, "r") as file:
        yaml_raw_data = yaml.safe_load(file)
    return yaml_raw_data

def serialize_data(data):
    serialized_data=[]
    for item in data:
        for key, coordinates in item.items():
            point_obj = Point(key, **coordinates)
            serialized_data.append(point_obj)
    return serialized_data

def num2words(num):
    under_20 = ['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven',
                'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
    above_100 = {100: 'Hundred', 1000: 'Thousand', 100000: 'Lack', 10000000: 'Crore'}

    if num < 20:
        return under_20[num]

    if num < 100:
        return tens[(int)(num / 10) - 2] + ('' if num % 10 == 0 else ' ' + under_20[int(num) % 10])

    # find the appropriate pivot - 'Million' in 3,603,550, or 'Thousand' in 603,550
    pivot = max([key for key in above_100.keys() if key <= num])

    return num2words((int)(num / pivot)) + ' ' + above_100[pivot] + ('' if num % pivot == 0 else ' ' + num2words(num % pivot))

def check_value_name(key,yaml_header_list, values,index=0):
    for d in yaml_header_list:
        if key.lower() ==str(d):
            d.value= values[key]
            return True
        if key.lower() ==d.label:
            d.value = values[key]
            return True
        if "," in d.label:
            labels=d.label.split(",")
            if key.lower() == labels[0]:
                for i in values.get(key,None):
                    check_value_name(i,yaml_header_list,values[key],index=1)
                return True
            labels=labels[index:]
            label=None
            new_value=values
            for label in labels:
                if new_value:
                    new_value=new_value.get(label,None)
            if label==key:
                d.value = new_value
                return True
    return None


class YamalReader:

    def __init__(self,name):
        self.name=name
        self.headers=[]
        self.footers=[]
        self.products=[]
        self.start=None
        self.serialize_data()

    def serialize_data(self):
        yaml_raw_data=get_yaml_data(self.name)
        self.headers=serialize_data(yaml_raw_data["Bill"]["harder"])
        self.footers=serialize_data(yaml_raw_data["Bill"]["footer"])
        self.products=serialize_data(yaml_raw_data["Bill"]["product"]["product_list"])
        if yaml_raw_data["Bill"]["product"].get("start"):
            self.start=yaml_raw_data["Bill"]["product"].get("start")


class FillValue:
    def __init__(self,data,yaml_obj):
        self.data=data
        self.yaml_obj=yaml_obj
        self.headers=self.yaml_obj.headers.copy()
        self.footers=self.yaml_obj.footers.copy()
        self.products=[]
        self.raw_footer_data={}
        self.set_header()
        self.set_products()
        self.set_footer()


    def set_header(self):
        for key in self.data.keys():
            check_value_name(
                key,
             yaml_header_list=self.headers,
             values=self.data)

    def set_products(self):
        start=self.yaml_obj.start
        total_amount=0
        gst_list=[]
        for index, product in enumerate(self.data.get("products")):
            print(index,start)
            callable_values=1
            other_callable_values=[]
            products_list=copy.deepcopy(self.yaml_obj.products)
            for product_properties in product.get("product_properties"):
                print(product_properties)
                is_show=product_properties.get("new_product_in_frontend").get("is_show",False)
                input_title=product_properties.get("new_product_in_frontend").get("input_title",'')
                is_calculable=product_properties.get("new_product_in_frontend").get("is_calculable",False)
                formula=product_properties.get("new_product_in_frontend").get("formula",'')
                value=product_properties.get("value")
                if input_title=="GST":
                    gst_list.append(int(value))
                for i in products_list:
                    if i.label=="s.no":
                        i.value=index+1
                        i.y=start
                        self.products.append(i)
                    if str(i)==input_title or str(i.label)==input_title:
                        if is_show:
                            i.value=value
                            i.y=start
                            self.products.append(i)
                if is_calculable and input_title!="GST":
                    if formula:
                        other_callable_values.append({"formula":formula,value:value})
                    else:
                        callable_values*=float(value if value else 1)
            for i in self.yaml_obj.products:
                i = copy.copy(i)
                if i.label=="amount":
                    i.value = round(callable_values,2)
                    i.y = start
                    self.products.append(i)
                    total_amount+=callable_values
            print([i.y for i in self.products])
            start-=15
        self.raw_footer_data["gst"]=round(sum(gst_list)/len(gst_list),2)
        self.raw_footer_data["gst_amount"]=round(total_amount*(self.raw_footer_data["gst"]/100),2)
        self.raw_footer_data["total_amount_with_out_gst"]=round(total_amount,2)
        self.raw_footer_data["total_amount_with_gst"]=round(total_amount+self.raw_footer_data["gst_amount"],2)
        self.raw_footer_data["total_amount_in_text"]=num2words(round(self.raw_footer_data["total_amount_with_gst"],2))
        self.raw_footer_data["center_gst"]=round(self.raw_footer_data["gst"]/2,2)
        self.raw_footer_data["state_gst"]=round(self.raw_footer_data["gst"]/2,2)
        self.raw_footer_data["center_gst_amount"]=round(self.raw_footer_data["gst_amount"]/2,2)
        self.raw_footer_data["state_gst_amount"]=round(self.raw_footer_data["gst_amount"]/2,2)

    def set_footer(self):
        for i in self.footers:

            i.value=self.raw_footer_data[i.label]

    def collect_all_data(self):
        data=[]
        data.extend(self.footers)
        data.extend(self.headers)
        data.extend(self.products)
        return copy.copy(data)




if __name__=="__main__":
    raw_data={
    "id": 2,
    "user": "yash",
    "invoice_number": 1,
    "receiver": {
        "id": 1,
        "name": "111",
        "user": "yash",
        "address": "kjhkjh",
        "gst_number": "jhhjkh",
        "state": "jkhk",
        "state_code": 5
    },
    "date": "2024-09-15",
    "products": [
        {
            "id": 8,
            "product_properties": [
                {
                    "id": 18,
                    "new_product_in_frontend": {
                        "id": 2,
                        "user": "yash",
                        "input_title": "quantity",
                        "size": "3.00",
                        "is_show": True,
                        "is_calculable": True,
                        "formula": ""
                    },
                    "value": "12"
                },
                {
                    "id": 19,
                    "new_product_in_frontend": {
                        "id": 1,
                        "user": "yash",
                        "input_title": "Name",
                        "size": "12.00",
                        "is_show": True,
                        "is_calculable": False,
                        "formula": ""
                    },
                    "value": "yash"
                },
                {
                    "id": 20,
                    "new_product_in_frontend": {
                        "id": 5,
                        "user": "yash",
                        "input_title": "size",
                        "size": "2.00",
                        "is_show": False,
                        "is_calculable": True,
                        "formula": ""
                    },
                    "value": "2"
                },
                {
                    "id": 21,
                    "new_product_in_frontend": {
                        "id": 3,
                        "user": "yash",
                        "input_title": "rate",
                        "size": "3.00",
                        "is_show": True,
                        "is_calculable": True,
                        "formula": ""
                    },
                    "value": "23"
                },
                {
                    "id": 22,
                    "new_product_in_frontend": {
                        "id": 4,
                        "user": "yash",
                        "input_title": "GST",
                        "size": "3.00",
                        "is_show": True,
                        "is_calculable": True,
                        "formula": ""
                    },
                    "value": "12"
                }
            ],
            "gst_amount": "0.00",
            "total_amount": "0.00"
        },
        {
            "id": 9,
            "product_properties": [
                {
                    "id": 23,
                    "new_product_in_frontend": {
                        "id": 1,
                        "user": "yash",
                        "input_title": "Name",
                        "size": "12.00",
                        "is_show": True,
                        "is_calculable": False,
                        "formula": ""
                    },
                    "value": "yash"
                },
                {
                    "id": 24,
                    "new_product_in_frontend": {
                        "id": 2,
                        "user": "yash",
                        "input_title": "quantity",
                        "size": "3.00",
                        "is_show": True,
                        "is_calculable": True,
                        "formula": ""
                    },
                    "value": "76"
                },
                {
                    "id": 25,
                    "new_product_in_frontend": {
                        "id": 3,
                        "user": "yash",
                        "input_title": "rate",
                        "size": "3.00",
                        "is_show": False,
                        "is_calculable": True,
                        "formula": ""
                    },
                    "value": "66"
                },
                {
                    "id": 26,
                    "new_product_in_frontend": {
                        "id": 5,
                        "user": "yash",
                        "input_title": "size",
                        "size": "2.00",
                        "is_show": False,
                        "is_calculable": True,
                        "formula": ""
                    },
                    "value": "666"
                },
                {
                    "id": 27,
                    "new_product_in_frontend": {
                        "id": 4,
                        "user": "yash",
                        "input_title": "GST",
                        "size": "3.00",
                        "is_show": True,
                        "is_calculable": True,
                        "formula": ""
                    },
                    "value": "12"
                }
            ],
            "gst_amount": "0.00",
            "total_amount": "0.00"
        }
    ],
    "gst_final_amount": None,
    "total_final_amount": None
}
    data=YamalReader("yash_adverting.yaml")
    fill_obj=FillValue(raw_data, data)
    k=Submit(fill_obj.collect_all_data()).draw_header_data()



