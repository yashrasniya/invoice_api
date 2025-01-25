import enum
import re

from numpy.core.defchararray import lower, title

from ocr.raw_data.states import indian_states


class PersonalInfo(enum.StrEnum):
    InvoiceNumber = enum.auto()
    InvoiceDate = enum.auto()
    State = enum.auto()
    Address = enum.auto()
    Name = enum.auto()
    GSTIN = enum.auto()
    CGST = enum.auto()
    SGST = enum.auto()
    IGST = enum.auto()

class TableHeaders(enum.Enum):
    ProductName=enum.auto()
    ProductCode=enum.auto()
    Quantity=enum.auto()
    Rate=enum.auto()
    Amount=enum.auto()
    S_No=enum.auto()

personal_info_patterns={
    r"\binvoice number\b":PersonalInfo.InvoiceNumber,
    r"Invoice No.":PersonalInfo.InvoiceNumber,
    r"Invoice Date":PersonalInfo.InvoiceDate,
    r"State":PersonalInfo.State,
    r"Address":PersonalInfo.Address,
    r"Name":PersonalInfo.Name,
    r"GSTIN":PersonalInfo.GSTIN,
    r"\binvoice date\b":PersonalInfo.InvoiceDate,
    r"CGST":PersonalInfo.CGST,
    r"SGST":PersonalInfo.SGST,
    r"IGST":PersonalInfo.IGST,
}

custom_check={
    PersonalInfo.InvoiceNumber:lambda w:bool(re.match(r'^[:\s]*[+-]?\d+$', w)),
    PersonalInfo.State:lambda w : title(w) in indian_states,
    TableHeaders.S_No:lambda w:bool(re.match(r'^[:\s]*[+-]?\d+$', w)),
    TableHeaders.Quantity:lambda w:bool(re.match(r'^\d+', w)),
    TableHeaders.Rate:lambda w:bool(re.match(r'^\d+|/-$', w)),
    TableHeaders.Amount:lambda w:bool(re.match(r'^\d+', w))
}

table_header_patterns={
    r"Name of Product":TableHeaders.ProductName,
    r"Particular":TableHeaders.ProductName,
    r"Hsn Code":TableHeaders.ProductCode,
    r"Quantity":TableHeaders.Quantity,
    r"Qty.":TableHeaders.Quantity,
    r"Rate":TableHeaders.Rate,
    r"Amount":TableHeaders.Amount,
    r"Amt.":TableHeaders.Amount,
    r"S.No.":TableHeaders.S_No,
}


remove_text_patterns=[
    r"\b(Total|Invoice|Amount|in|Words|CMYK|thundred|Bank|Two|Receiver's|Details|Thousand)\b",

]