import qrcode

# Link you want to encode
upi_id = "yashrasniya3@okaxis"
merchant_name = 'yash'
amount = '111'
link = f"upi://pay?pa={upi_id}&pn={merchant_name}&tn=undefined&am={amount}"

# Create QR code
qr = qrcode.QRCode(
    version=1,  # controls size (1 = smallest, 40 = largest)
    error_correction=qrcode.constants.ERROR_CORRECT_H,  # High error correction
    box_size=10,  # size of each box in pixels
    border=4,  # thickness of border
)

qr.add_data(link)
qr.make(fit=True)

# Create an image from the QR Code instance
img = qr.make_image(fill_color="black", back_color="white")

# Save the image
img.save("qr_code.png")

print("QR code generated and saved as qr_code.png")
